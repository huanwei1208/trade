"""Bus handlers — now managed via pipeline_dag.

Handlers are no longer defined here. Instead, bootstrap_from_dag() in
trade_py/bus/__init__.py reads the pipeline_dag table and creates
handlers dynamically.

To view/modify the DAG:
  trade event dag            # view current DAG
  trade event enable <job>   # enable a job
  trade event disable <job>  # disable a job
"""
