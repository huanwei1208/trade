"""Handler modules for the EventBus.

Each module exposes register(bus, data_root) which subscribes handlers to topics.
Business logic stays in trade_py/jobs/__init__.py; handlers are pure routing.
"""
