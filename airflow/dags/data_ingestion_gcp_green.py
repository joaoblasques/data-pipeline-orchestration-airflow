import os
from datetime import datetime

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from airflow.providers.google.cloud.operators.bigquery import BigQueryInsertJobOperator
from airflow.providers.google.cloud.hooks.gcs import GCSHook
import requests
import gzip
import shutil
import pyarrow
import pyarrow.csv
import pyarrow.parquet 



# Make sure the values ​​match your gcp values
PROJECT_ID="ny-taxi-464111"
BUCKET="ny-taxi-464111-bucket"
BIGQUERY_DATASET = "ny_taxi_464111_bigquery_dataset"
path_to_local_home = os.environ.get("AIRFLOW_HOME", "/opt/airflow/")

# Utility functions
def download(file_gz, file_csv, url):

    # Download the CSV.GZ file
    response = requests.get(url)
    if response.status_code == 200:
        with open(file_gz, 'wb') as f_out:
            f_out.write(response.content)
    else:
        print(f"Error downloading file: {response.status_code}")
        return False
    
    # Unzip the CSV file
    with gzip.open(file_gz, 'rb') as f_in:
        with open(file_csv, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
    

def format_to_parquet(src_file):

    table = pyarrow.csv.read_csv(src_file)

    # change ehail_fee to float64
    if 'ehail_fee' in table.column_names:
        # Convertir la columna 'ehail_fee' a float (FLOAT64)
        table = table.set_column(
            table.schema.get_field_index('ehail_fee'),
            'ehail_fee',
            pyarrow.array(table['ehail_fee'].to_pandas().astype('float64'))  
        )

    pyarrow.parquet.write_table(table, src_file.replace('.csv', '.parquet'))



def upload_to_gcs(bucket, object_name, local_file, gcp_conn_id="gcp-airflow"):
    hook = GCSHook(gcp_conn_id)
    hook.upload(
        bucket_name=bucket,
        object_name=object_name,
        filename=local_file,
        timeout=600
    )


# Defining the DAG
dag = DAG(
    "GCP_ingestion_green",
    schedule_interval="0 6 2 * *",
    start_date=datetime(2019, 1, 1),
    end_date=datetime(2019, 12, 31),
    catchup=True, 
    max_active_runs=1,
)

table_name_template = 'green_taxi_{{ execution_date.strftime(\'%Y_%m\') }}'
file_template_csv_gz = 'output_{{ execution_date.strftime(\'%Y_%m\') }}.csv.gz'
file_template_csv = 'output_{{ execution_date.strftime(\'%Y_%m\') }}.csv'
file_template_parquet = 'output_{{ execution_date.strftime(\'%Y_%m\') }}.parquet'
consolidated_table_name = "green_{{ execution_date.strftime(\'%Y\') }}"
url_template = "https://github.com/DataTalksClub/nyc-tlc-data/releases/download/green/green_tripdata_{{ execution_date.strftime(\'%Y-%m\') }}.csv.gz"


# Task 1: Download and unzip file
download_task = PythonOperator(
    task_id="download",
    python_callable=download,
    op_kwargs={
        'file_gz': file_template_csv_gz,
        'file_csv': file_template_csv,
        'file_parquet': file_template_parquet,
        'url': url_template
    },
    retries=10,
    dag=dag
)

# Task 2: Format to parquet
process_task = PythonOperator(
    task_id="format_to_parquet",
    python_callable=format_to_parquet,
    op_kwargs={
        "src_file": f"{path_to_local_home}/{file_template_csv}"
    },
    retries=10,
    dag=dag
)


# Task 3: Upload file to google storage
local_to_gcs_task = PythonOperator(
    task_id="upload_to_gcs",
    python_callable=upload_to_gcs,
    op_kwargs={
        "bucket": BUCKET,
        "object_name": f"raw/{file_template_parquet}",
        "local_file": f"{path_to_local_home}/{file_template_parquet}",
        "gcp_conn_id": "gcp-airflow"
    },
    retries=10,
    dag=dag
)

# Task 4: Create final table
create_final_table_task = BigQueryInsertJobOperator(
    task_id="create_final_table",
    gcp_conn_id="gcp-airflow",
    configuration={
        "query": {
            "query": f"""
                CREATE TABLE IF NOT EXISTS `{PROJECT_ID}.{BIGQUERY_DATASET}.{consolidated_table_name}`
                (
                    unique_row_id BYTES,
                    filename STRING,      
                    VendorID INT64,
                    lpep_pickup_datetime TIMESTAMP,
                    lpep_dropoff_datetime TIMESTAMP,
                    store_and_fwd_flag STRING,
                    RatecodeID INT64,
                    PULocationID INT64,
                    DOLocationID INT64,
                    passenger_count INT64,
                    trip_distance FLOAT64,
                    fare_amount FLOAT64,
                    extra FLOAT64,
                    mta_tax FLOAT64,
                    tip_amount FLOAT64,
                    tolls_amount FLOAT64,
                    ehail_fee FLOAT64,
                    improvement_surcharge FLOAT64,
                    total_amount FLOAT64,
                    payment_type INT64,
                    trip_type INT64,
                    congestion_surcharge FLOAT64
                )    
            """,
            "useLegacySql": False,
        }
    },
    retries=3,
    dag=dag,
)

# Task 5: Create external monthly table
create_external_table_task = BigQueryInsertJobOperator(
    task_id="create_external_table",
    gcp_conn_id="gcp-airflow",
    configuration={
        "query": {
            "query": f"""
                CREATE OR REPLACE EXTERNAL TABLE `{PROJECT_ID}.{BIGQUERY_DATASET}.{table_name_template}_ext`
                (
                    VendorID INT64,
                    lpep_pickup_datetime TIMESTAMP,
                    lpep_dropoff_datetime TIMESTAMP,
                    store_and_fwd_flag STRING,
                    RatecodeID INT64,
                    PULocationID INT64,
                    DOLocationID INT64,
                    passenger_count INT64,
                    trip_distance FLOAT64,
                    fare_amount FLOAT64,
                    extra FLOAT64,
                    mta_tax FLOAT64,
                    tip_amount FLOAT64,
                    tolls_amount FLOAT64,
                    ehail_fee FLOAT64,
                    improvement_surcharge FLOAT64,
                    total_amount FLOAT64,
                    payment_type INT64,
                    trip_type INT64,
                    congestion_surcharge FLOAT64
                )
                OPTIONS (
                    uris = ['gs://{BUCKET}/raw/{file_template_parquet}'],
                    format = 'PARQUET'
                );
            """,
            "useLegacySql": False,
        }
    },
    retries=3,
    dag=dag
)

# Task 6: Create native monthly table
create_temp_table_task = BigQueryInsertJobOperator(
    task_id="create_temp_table",
    gcp_conn_id="gcp-airflow",
    configuration={
        "query": {
            "query": f"""
                CREATE OR REPLACE TABLE `{PROJECT_ID}.{BIGQUERY_DATASET}.{table_name_template}_tmp`
                AS
                SELECT
                    MD5(CONCAT(
                        COALESCE(CAST(VendorID AS STRING), ""),
                        COALESCE(CAST(lpep_pickup_datetime AS STRING), ""),
                        COALESCE(CAST(lpep_dropoff_datetime AS STRING), ""),
                        COALESCE(CAST(PULocationID AS STRING), ""),
                        COALESCE(CAST(DOLocationID AS STRING), "")
                    )) AS unique_row_id,
                    "{file_template_parquet}" AS filename,
                    *
                FROM `{PROJECT_ID}.{BIGQUERY_DATASET}.{table_name_template}_ext`;
            """,
            "useLegacySql": False,
        }
    },
    retries=3,
    dag=dag,
)


# Task 7: Merge
merge_to_final_table_task = BigQueryInsertJobOperator(
    task_id="merge_to_final_table",
    gcp_conn_id="gcp-airflow",
    configuration={
        "query": {
            "query": f"""
                MERGE INTO `{PROJECT_ID}.{BIGQUERY_DATASET}.{consolidated_table_name}` T
                USING `{PROJECT_ID}.{BIGQUERY_DATASET}.{table_name_template}_tmp` S
                ON T.unique_row_id = S.unique_row_id
                WHEN NOT MATCHED THEN
                    INSERT (unique_row_id, filename, VendorID, lpep_pickup_datetime, lpep_dropoff_datetime, store_and_fwd_flag, RatecodeID, PULocationID, DOLocationID, passenger_count, trip_distance, fare_amount, extra, mta_tax, tip_amount, tolls_amount, ehail_fee, improvement_surcharge, total_amount, payment_type, trip_type, congestion_surcharge)
                    VALUES (S.unique_row_id, S.filename, S.VendorID, S.lpep_pickup_datetime, S.lpep_dropoff_datetime, S.store_and_fwd_flag, S.RatecodeID, S.PULocationID, S.DOLocationID, S.passenger_count, S.trip_distance, S.fare_amount, S.extra, S.mta_tax, S.tip_amount, S.tolls_amount, S.ehail_fee, S.improvement_surcharge, S.total_amount, S.payment_type, S.trip_type, S.congestion_surcharge);
            """,
            "useLegacySql": False,
        }
    },
    retries=3,
    dag=dag,
)

# Task 8: Delete local files after upload
cleanup_task = BashOperator(
    task_id="cleanup_files",
    bash_command=f"rm -f {path_to_local_home}/{file_template_csv_gz} {path_to_local_home}/{file_template_csv} {path_to_local_home}/{file_template_parquet}",
    dag=dag,
)


download_task >> process_task >> local_to_gcs_task >> create_final_table_task >> create_external_table_task >> create_temp_table_task >> merge_to_final_table_task >> cleanup_task