.. _gateway_api:

==================
Gateway REST API
==================

The Qiskit Serverless Gateway REST API allows you to manage quantum programs and jobs programmatically.

.. toctree::
   :maxdepth: 1

   authentication
   endpoints

Quick Start
===========

Base URL
--------

.. code-block:: text

   https://qiskit-serverless.quantum.ibm.com/api/v1/

Authentication
--------------

All requests require a Bearer token:

.. code-block:: bash

   curl -H "Authorization: Bearer <your-token>" \
     https://qiskit-serverless.quantum.ibm.com/api/v1/jobs/

Response Format
---------------

Responses are JSON with standard HTTP status codes:

* ``200`` - Success
* ``400`` - Bad request
* ``401`` - Unauthorized
* ``404`` - Not found

Pagination
----------

List endpoints support ``limit`` and ``offset`` parameters:

.. code-block:: bash

   curl -H "Authorization: Bearer <token>" \
     "https://qiskit-serverless.quantum.ibm.com/api/v1/jobs/?limit=10&offset=0"

OpenAPI Schema
==============

The OpenAPI specification is available at:

* **JSON**: https://qiskit-serverless.quantum.ibm.com/swagger.json
* **YAML**: https://qiskit-serverless.quantum.ibm.com/swagger.yaml

.. Made with Bob
