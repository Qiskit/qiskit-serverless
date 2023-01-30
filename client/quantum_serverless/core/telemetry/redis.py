

def emit_metrics_to_redis():
    # inject execution meta emitter
    if events is not None:
        emitter = events
    else:
        emitter = RedisEventHandler.from_env_vars()
    if emitter is not None:
        emitter.publish(
            META_TOPIC,
            message=ExecutionMessage(
                workload_id=os.environ.get(QS_EXECUTION_WORKLOAD_ID),
                uid=os.environ.get(QS_EXECUTION_UID),
                layer="qs",
                function_meta={"name": function.__name__},
                resources=remote_target.to_dict(),
            ).to_dict(),
        )