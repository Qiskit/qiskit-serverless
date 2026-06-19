.. _custom_images:

==============
Custom Images
==============

This section provides guidance for building and deploying custom Docker images as Qiskit Functions.

Custom images allow providers to:

* Include specialized dependencies and libraries
* Use specific Python versions or system packages
* Pre-install large datasets or models
* Optimize runtime performance
* Create reusable function templates

This is an advanced feature typically used by function providers who need full control over the execution environment.

.. note::

   Developing custom images locally on an Apple Silicon (M-series) Mac? See
   :ref:`run_on_apple_silicon` for a native arm64 path that avoids Ray startup timeouts.

.. toctree::
   :maxdepth: 1

   deploy_custom_image_function
   custom_image_examples
   run_on_apple_silicon
