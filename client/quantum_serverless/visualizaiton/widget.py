# This code is a Qiskit project.
#
# (C) Copyright IBM 2023.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""
===========================================================
Decorators (:mod:`quantum_serverless.visualization.widget`)
===========================================================

.. currentmodule:: quantum_serverless.visualization.widget

Quantum serverless widgets
==========================

.. autosummary::
    :toctree: ../stubs/

    Widget
"""
from IPython.display import display, clear_output
from ipywidgets import GridspecLayout, AppLayout, widgets

from quantum_serverless import Provider


class Widget:
    def __init__(self, provider: Provider):
        self.provider = provider
        self.list_view = widgets.Output()
        with self.list_view:
            display(self.render_list())

        self.pagination_view = widgets.Output()
        with self.pagination_view:
            display(self.render_pagination())

    def render_list(self):
        pass

    def render_pagination(self):
        pass

    def search(self):
        pass

    def show(self):
        grid = GridspecLayout(2, 1, height="500px")
        grid[0, 0] = self.list_view
        grid[1, 0] = self.pagination_view

        return AppLayout(
            header=self.search(),
            left_sidebar=None,
            center=grid,
            right_sidebar=None,
            footer=None,
            pane_widths=[0.5, 1, 1],
            pane_heights=[0.5, 5, 1],
        )
