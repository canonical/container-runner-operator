#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import os
import secrets
import time

import grpc
import ratings_api.ratings_features_user_pb2 as pb2
import ratings_api.ratings_features_user_pb2_grpc as pb2_grpc
import requests
from pytest import mark
from pytest_operator.plugin import OpsTest

CONTAINER_RUNNER = "container-runner"
UNIT_0 = f"{CONTAINER_RUNNER}/0"
DB = "db"

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", ".."))


@mark.abort_on_fail
@mark.skip_if_deployed
async def test_deploy(ops_test: OpsTest, container_runner_charm):
    config = {
        "container-image-uri": "ghcr.io/ubuntu/app-center-ratings:sha-7f05d08",
        "host-port": 81,
        "container-port": 81,
        "database-expected": True,
    }
    resources = {"env-file": f"{BASE_DIR}/tests/integration/env-vars.env"}
    await ops_test.model.deploy(
        await container_runner_charm,
        application_name=CONTAINER_RUNNER,
        config=config,
        resources=resources,
    )
    # issuing dummy update_status just to trigger an event
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(apps=[CONTAINER_RUNNER], status="waiting", timeout=1000)
        assert ops_test.model.applications[CONTAINER_RUNNER].units[0].workload_status == "waiting"


@mark.abort_on_fail
async def test_database_relation(ops_test: OpsTest):
    """Test that the charm can be successfully related to PostgreSQL."""
    await asyncio.gather(
        ops_test.model.deploy("postgresql", channel="edge", application_name=DB, trust=True),
        ops_test.model.wait_for_idle(
            apps=[DB], status="active", raise_on_blocked=True, timeout=1000
        ),
    )

    await asyncio.gather(
        ops_test.model.integrate(CONTAINER_RUNNER, DB),
        ops_test.model.wait_for_idle(
            apps=[CONTAINER_RUNNER], status="active", raise_on_blocked=True, timeout=1000
        ),
    )


@mark.abort_on_fail
async def test_hello_world_image(ops_test: OpsTest):
    """Test that the charm can deploy a container that can then be reached via curl."""
    status = await ops_test.model.get_status()  # noqa: F821
    unit = list(status.applications[CONTAINER_RUNNER].units)[0]
    print(f"Connecting to address: {status}")
    address = status["applications"][CONTAINER_RUNNER]["units"][unit]["public-address"]
    print(f"Connecting to address: {address}")
    connection_string = f"{address}:81"

    channel = grpc.insecure_channel(connection_string)
    stub = pb2_grpc.UserStub(channel)
    message = pb2.AuthenticateRequest(id=secrets.token_hex(32))
    print(f"Message sent: {message}")
    response = stub.Authenticate(message)
    assert response.token


@mark.abort_on_fail
async def test_config_update(ops_test: OpsTest):
    """Test that the charm can update config while running to redeploy a different image on a different port."""
    await ops_test.model.applications[CONTAINER_RUNNER].set_config(
        {
            "host-port": "5678",
            "container-port": "5678",
            "container-image-uri": "hashicorp/http-echo",
            "database-expected": "false",
        }
    )
    await ops_test.model.wait_for_idle(
        apps=[CONTAINER_RUNNER], status="active", raise_on_blocked=True, timeout=1000
    )
    time.sleep(10)
    status = await ops_test.model.get_status()  # noqa: F821
    unit = list(status.applications[CONTAINER_RUNNER].units)[0]
    print(f"Connecting to address: {status}")
    address = status["applications"][CONTAINER_RUNNER]["units"][unit]["public-address"]
    print(f"Connecting to address: {address}")
    connection_string = f"http://{address}:5678"

    response = requests.get(connection_string)
    assert "hello-world" in response.text
