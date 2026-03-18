.. _gateway_api_authentication:

==============
Authentication
==============

All API requests require authentication using a Bearer token.

Token Authentication
====================

Include your token in the ``Authorization`` header:

.. code-block:: bash

   Authorization: Bearer <your-token>

Example Request
===============

.. code-block:: bash

   curl -H "Authorization: Bearer your-token" \
     https://qiskit-serverless.quantum.ibm.com/api/v1/jobs/

Python Example
--------------

.. code-block:: python

   import requests

   headers = {"Authorization": "Bearer your-token"}
   response = requests.get(
       "https://qiskit-serverless.quantum.ibm.com/api/v1/jobs/",
       headers=headers
   )

Error Responses
===============

**401 Unauthorized** - Missing or invalid token

.. code-block:: json

   {
     "detail": "Authentication credentials were not provided."
   }

**403 Forbidden** - Insufficient permissions

.. code-block:: json

   {
     "message": "Not allowed to perform this action."
   }

Authentication Methods
======================

The Gateway supports multiple authentication backends configured via ``SETTINGS_AUTH_MECHANISM``:

* **mock_token** - Development only, accepts any token
* **custom_token** - Validates against external API
* **qiskit_ibm_runtime** - IBM Quantum Platform integration

Best Practices
==============

* Never commit tokens to version control
* Use environment variables for token storage
* Always use HTTPS in production
* Rotate tokens regularly

.. Made with Bob
