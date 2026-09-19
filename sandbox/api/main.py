"""
AutoOps sandbox "api" service - the front door of the demo application
that AutoOps watches over. Deliberately simple: a couple of in-memory
routes plus behavior hooks driven by environment variables, so the chaos
scripts (sandbox/chaos/*.sh) can flip it into a failure mode on a real
cluster and produce genuine logs/metrics for Cloud Logging and Cloud
Monitoring to pick up.
"""
import json
import logging
import os
import sys
import time

from fastapi import FastAPI, HTTPException

logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
logger = logging.getLogger("api")

DB_HOST = os.getenv("DB_HOST", "cloudsql-primary")
SIMULATE_DB_DOWN = DB_HOST != "cloudsql-primary"  # flips true if the ConfigMap was set wrong

app = FastAPI(title="AutoOps Sandbox API")

_orders = {1: {"id": 1, "item": "widget", "qty": 3}}
_users = {42: {"id": 42, "name": "Jordan"}}
_start_time = time.time()


def _log(level: str, message: str) -> None:
    getattr(logger, level)(json.dumps({"service": "api", "message": message, "db_host": DB_HOST}))


@app.get("/health")
def health():
    if SIMULATE_DB_DOWN:
        _log("error", f'could not translate host name "{DB_HOST}" to address: Name or service not known')
        raise HTTPException(500, "database unreachable")
    return {"status": "ok", "db_host": DB_HOST, "uptime_s": round(time.time() - _start_time, 1)}


@app.get("/orders/{order_id}")
def get_order(order_id: int):
    if SIMULATE_DB_DOWN:
        _log("error", "500 Internal Server Error on GET /orders: database unreachable")
        raise HTTPException(500, "database unreachable")
    order = _orders.get(order_id)
    if not order:
        raise HTTPException(404, "order not found")
    return order


@app.get("/users/{user_id}")
def get_user(user_id: int):
    if SIMULATE_DB_DOWN:
        _log("error", f"500 Internal Server Error on GET /users/{user_id}: database unreachable")
        raise HTTPException(500, "database unreachable")
    user = _users.get(user_id)
    if not user:
        raise HTTPException(404, "user not found")
    return user
