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
from typing import List

from IPython.display import display, clear_output
from ipywidgets import GridspecLayout, widgets, Layout

from quantum_serverless import Provider
from quantum_serverless.core.job import Job
from quantum_serverless.exception import QuantumServerlessException


class Widget:
    """Widget for displaying information related to provider."""

    def __init__(self, provider: Provider):
        """Constructor for widget.

        Args:
            provider: provider
        """
        if provider is None:
            raise QuantumServerlessException(
                "Provider must be set in order to display widget."
            )
        self.provider = provider

        self.offset = 0
        self.limit = 10
        self.jobs: List[Job] = self.provider.get_jobs()

        self.list_view = widgets.Output()
        with self.list_view:
            display(self.render_list())

        self.pagination_view = widgets.Output()
        with self.pagination_view:
            display(self.render_pagination())

    def render_list(self):
        """Renders list of jobs."""

        def render_details(job: Job):
            """Renders single instance of job."""
            return widgets.HTML(
                f"""
                <div>
                    <div>
                        <b>Status</b>: {job.raw_data.get("status", "")}
                        <br/>
                        <b>Result</b>: {job.raw_data.get("result", "")}
                    </div>
                </div>
                """
            )

        accordion = widgets.Accordion(
            children=[render_details(job) for job in self.jobs]
        )

        for idx, job in enumerate(self.jobs):
            prefix = job.raw_data.get("program", {}).get("title", "Job")
            accordion.set_title(idx, f'"{prefix}" #{job.job_id}')
        return accordion

    def render_pagination(self):
        """Renders pagination."""

        def paginate(page_button):
            """Handles pagination callback logic."""
            if page_button.tooltip == "prev":
                self.jobs = self.provider.get_jobs(
                    limit=self.limit, offset=self.offset - self.limit
                )
                self.offset = self.offset - self.limit
            elif page_button.tooltip == "next":
                self.jobs = self.provider.get_jobs(
                    limit=self.limit, offset=self.offset + self.limit
                )
                self.offset = self.offset + self.limit
            with self.list_view:
                clear_output()
                display(self.render_list())
            with self.pagination_view:
                clear_output()
                display(self.render_pagination())

        prev_page = widgets.Button(
            description="Prev",
            disabled=self.offset < 1,
            button_style="",
            tooltip="prev",
            icon="arrow-circle-left",
        )
        prev_page.on_click(paginate)
        prev_page.layout = Layout(width="33%")

        next_page = widgets.Button(
            description="Next",
            disabled=len(self.jobs) != self.limit,
            button_style="",
            tooltip="next",
            icon="arrow-circle-right",
        )
        next_page.on_click(paginate)
        next_page.layout = Layout(width="33%")

        pagination_number = widgets.Button(
            description=f"{self.offset}-{self.offset + self.limit}",
            disabled=True,
            button_style="",
            tooltip="items",
            icon="list",
        )
        pagination_number.layout = Layout(width="33%")

        return widgets.HBox([prev_page, pagination_number, next_page])

    def header_view(self):
        """Renders header of widget."""
        return widgets.Button(
            description=f"QuantumServerless [{self.provider.name}]",
            button_style="info",
            layout=Layout(height="auto", width="auto"),
            disabled=True,
        )

    def show(self):
        """Displays widget."""
        grid = GridspecLayout(10, 1, height="500px", width="600px")
        grid[:1, 0] = self.header_view()
        grid[1:2, 0] = self.pagination_view
        grid[2:, 0] = self.list_view

        return grid
