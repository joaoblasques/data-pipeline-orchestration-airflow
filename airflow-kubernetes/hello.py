from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime

# Definimos el DAG
dag = DAG(
    'hello_world_dag',  # Nombre del DAG
    description='Un simple DAG que imprime Hello World',
    schedule_interval=None,  # No se ejecuta automáticamente, solo de manera manual
    start_date=datetime(2025, 1, 6),  # Fecha de inicio
    catchup=False  # No hace backfill para fechas previas
)

# Definimos la tarea con BashOperator
hello_world_task = BashOperator(
    task_id='hello_world_task',  # ID de la tarea
    bash_command='echo "Hello World"',  # Comando que se ejecutará
    dag=dag
)

# Dependencias: En este caso solo tenemos una tarea, no hay que agregar dependencias adicionales
hello_world_task