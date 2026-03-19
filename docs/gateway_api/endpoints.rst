.. _gateway_api_endpoints:

=========
Endpoints
=========

All endpoints are prefixed with ``/api/v1/``

Programs
========

Manage quantum programs (functions).

List Programs
-------------

``GET /programs/``

List all accessible programs.

**Query Parameters:**

* ``filter`` (optional) - Filter by type: ``serverless`` or ``catalog``

**Response:**

.. code-block:: json

   [
     {
       "id": "123e4567-e89b-12d3-a456-426614174000",
       "title": "my-function",
       "entrypoint": "main.py",
       "dependencies": ["qiskit==1.0.0"],
       "provider": null,
       "type": "GENERIC",
       "version": "1.0.0"
     }
   ]

Get Program by Title
--------------------

``GET /programs/get_by_title/{title}/``

Retrieve a program by its title.

**Query Parameters:**

* ``provider`` (optional) - Provider name if program is provider-owned

Upload Program
--------------

``POST /programs/upload/``

Upload a new program.

**Request Body:** Multipart form data

* ``title`` (required) - Program title
* ``entrypoint`` (required) - Entry point file
* ``artifact`` (required) - Program artifact (.tar file)
* ``dependencies`` (optional) - List of dependencies
* ``description`` (optional) - Program description

Run Program
-----------

``POST /programs/run/``

Execute a program and create a job.

**Request Body:**

.. code-block:: json

   {
     "title": "my-function",
     "arguments": {
       "param1": "value1"
     },
     "config": {
       "workers": 2,
       "auto_scaling": true
     }
   }

**Response:**

.. code-block:: json

   {
     "id": "987fcdeb-51a2-43f1-b789-123456789abc",
     "status": "QUEUED"
   }

Jobs
====

Manage job execution and monitoring.

List Jobs
---------

``GET /jobs/``

List jobs with optional filtering.

**Query Parameters:**

* ``function`` (optional) - Filter by function title
* ``provider`` (optional) - Filter by provider
* ``status`` (optional) - Filter by job status
* ``filter`` (optional) - Type: ``catalog`` or ``serverless``
* ``limit`` (optional) - Results per page (default: 10)
* ``offset`` (optional) - Number of results to skip (default: 0)
* ``created_after`` (optional) - ISO 8601 datetime filter

**Response:**

.. code-block:: json

   {
     "count": 42,
     "next": "https://qiskit-serverless.quantum.ibm.com/api/v1/jobs/?limit=10&offset=10",
     "previous": null,
     "results": [
       {
         "id": "987fcdeb-51a2-43f1-b789-123456789abc",
         "status": "SUCCEEDED",
         "program": {
           "id": "123e4567-e89b-12d3-a456-426614174000",
           "title": "my-function"
         },
         "created": "2024-01-15T10:30:00Z"
       }
     ]
   }

Get Job
-------

``GET /jobs/{job_id}/``

Retrieve a specific job by ID.

**Query Parameters:**

* ``with_result`` (optional) - Include result field (default: true)

**Response:**

.. code-block:: json

   {
     "id": "987fcdeb-51a2-43f1-b789-123456789abc",
     "status": "SUCCEEDED",
     "result": {
       "counts": {"00": 512, "11": 512}
     },
     "program": {
       "id": "123e4567-e89b-12d3-a456-426614174000",
       "title": "my-function"
     },
     "created": "2024-01-15T10:30:00Z"
   }

Get Job Logs
------------

``GET /jobs/{job_id}/logs/``

Retrieve execution logs for a job.

**Response:**

.. code-block:: json

   {
     "logs": "Job started...\nExecuting quantum circuit...\nJob completed."
   }

Stop Job
--------

``POST /jobs/{job_id}/stop/``

Stop a running job.

**Request Body:**

.. code-block:: json

   {
     "service": "ray"
   }

**Response:**

.. code-block:: json

   {
     "message": "Job stopped successfully"
   }

Files
=====

Manage files associated with programs.

Upload File
-----------

``POST /files/upload/``

Upload a file to user storage.

**Query Parameters:**

* ``function`` (required) - Function title
* ``provider`` (optional) - Provider name

**Request Body:** Multipart form data with ``file`` field

Download File
-------------

``GET /files/download/``

Download a file from user storage.

**Query Parameters:**

* ``function`` (required) - Function title
* ``file`` (required) - File name
* ``provider`` (optional) - Provider name

List Files
----------

``GET /files/list/``

List files in user storage.

**Query Parameters:**

* ``function`` (required) - Function title
* ``provider`` (optional) - Provider name

**Response:**

.. code-block:: json

   {
     "files": ["data.txt", "results.json"]
   }

Delete File
-----------

``DELETE /files/delete/``

Delete a file from user storage.

**Query Parameters:**

* ``function`` (required) - Function title
* ``file`` (required) - File name
* ``provider`` (optional) - Provider name

System
======

Health checks and system information.

Version
-------

``GET /version/``

Get Gateway version information.

**Authentication:** Not required

**Response:**

.. code-block:: json

   {
     "version": "0.30.0"
   }

Readiness Probe
---------------

``GET /readiness/``

Check if the Gateway is ready to accept requests.

**Authentication:** Not required

Liveness Probe
--------------

``GET /liveness/``

Check if the Gateway is alive.

**Authentication:** Not required

Job Status Values
=================

* ``QUEUED`` - Job created, waiting for scheduling
* ``PENDING`` - Submitted to Ray, waiting to start
* ``RUNNING`` - Currently executing
* ``SUCCEEDED`` - Completed successfully
* ``FAILED`` - Execution failed
* ``STOPPED`` - Manually stopped by user

.. Made with Bob
