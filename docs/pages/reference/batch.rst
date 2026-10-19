Batch scanning
----------------

These helpers work on whole directory trees. They build on the single name
validators and never change their rules.

.. autofunction:: pathvalidate.scan_paths

.. autofunction:: pathvalidate.plan_fixes

.. autofunction:: pathvalidate.apply_fixes

.. autofunction:: pathvalidate.split_name

.. autofunction:: pathvalidate.fit_length

.. autofunction:: pathvalidate.decode_wsl_name

.. autofunction:: pathvalidate.has_wsl_mapping

Classes
~~~~~~~~~

.. autoclass:: pathvalidate.ScanResult
   :members:

.. autoclass:: pathvalidate.PathReport
   :members:

.. autoclass:: pathvalidate.Issue
   :members:

.. autoclass:: pathvalidate.FixPlan
   :members:

.. autoclass:: pathvalidate.Rename
   :members:

.. autoclass:: pathvalidate.ApplyResult
   :members:

.. autoclass:: pathvalidate.BatchRenameError
   :members:
