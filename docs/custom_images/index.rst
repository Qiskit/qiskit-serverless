.. _custom_images:

==============
Custom Images
==============

This section provides guidance for building and deploying custom Docker images as IBM Quantum
Functions (formerly Qiskit Functions).

Custom images allow providers to:

* Include specialized dependencies and libraries
* Use specific Python versions or system packages
* Pre-install large datasets or models
* Optimize runtime performance
* Create reusable function templates

This is an advanced feature typically used by function providers who need full control over the execution environment.

.. important::

   The ``Runner`` class contract and upload/run API are the same for both engines — only the
   base image differs (``ray-node`` vs. ``fleet-node:base``); both are shown throughout this
   section. Building and running the image locally only has a documented path for Ray today; see
   :ref:`deploy_image` for why. For a Fleets walkthrough with the default image, see
   :ref:`fleets_tutorials`. See :ref:`concepts` for how Ray relates to Fleets generally.

.. note::

   Developing custom images locally on an Apple Silicon (M-series) Mac? See
   :ref:`run_on_apple_silicon` for a native arm64 path that avoids Ray startup timeouts.

.. toctree::
   :maxdepth: 1

   deploy_custom_image_function
   custom_image_examples
   run_on_apple_silicon
