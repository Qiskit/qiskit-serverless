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
import os
from datetime import datetime

from IPython.display import display, clear_output
from ipywidgets import GridspecLayout, widgets, Layout

from quantum_serverless.exception import QuantumServerlessException

TABLE_STYLE = """
<style>
    table {
        width: 100% !important;
        font-family:IBM Plex Sans, Arial, sans-serif !important;
    }

    th, td {
        text-align: left !important;
        padding: 5px !important;
    }

    tr:nth-child(even) {background-color: #f6f6f6 !important;}
</style>
"""


class Widget:
    """Widget for displaying information related to provider."""

    def __init__(self, provider):
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
        self.jobs = self.provider.get_jobs()

        self.list_view = widgets.Output()
        with self.list_view:
            display(self.render_list())

        self.pagination_view = widgets.Output()
        with self.pagination_view:
            display(self.render_pagination())

        self.information_view = widgets.Output()
        with self.information_view:
            display(self.render_information())

    def render_list(self):
        """Renders list of jobs."""

        def render_html_row(job):
            title = job.raw_data.get("program", {}).get("title", "Job")
            status = job.raw_data.get("status", "").lower()
            date = datetime.strptime(
                job.raw_data.get("created", "2011-11-11T11:11:11.000Z"),
                "%Y-%m-%dT%H:%M:%S.%fZ",
            ).strftime("%m/%d/%Y")
            status_style_map = {"succeeded": "color:green;", "failed": "color:red;"}

            return f"""
                <tr>
                    <td>{job.job_id}</td>
                    <td>{title}</td>
                    <td style={status_style_map.get(status, "")}>{status}</td>
                    <td>{date}</td>
                </tr>
            """

        rows = "\n".join([render_html_row(job) for job in self.jobs])

        table = f"""
            <table>
                {TABLE_STYLE}
                <tr>
                    <th>ID</th>
                    <th>Title</th>
                    <th>Status</th>
                    <th>Creation date</th>
                </tr>
                {rows}
            </table>
        """
        return widgets.HTML(table)

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

    def render_information(self):
        """Renders information widget."""
        client_version = "Unknown"
        version_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "VERSION.txt"
        )
        if os.path.exists(version_file_path):
            with open(version_file_path, "r", encoding="utf-8") as version_file:
                client_version = version_file.read().strip()

        table = f"""
            <table>
                {TABLE_STYLE}
                <tr>
                    <th>Parameter</th>
                    <th>Value</th>
                </tr>
                <tr>
                    <td>Provider</td>
                    <td>{self.provider.name}</td>
                </tr>
                <tr>
                    <td>Software version</td>
                    <td>{client_version}</td>
                </tr>
            </table>
        """
        return widgets.HTML(table)

    def show(self):
        """Displays widget."""
        job_list_widget = GridspecLayout(10, 2)
        job_list_widget[:9, :] = self.list_view
        job_list_widget[9:, 1] = self.pagination_view

        tab_nest = widgets.Tab()
        tab_nest.children = [job_list_widget, self.render_information()]
        tab_nest.set_title(0, "Program runs")
        tab_nest.set_title(1, "Info")

        return tab_nest
