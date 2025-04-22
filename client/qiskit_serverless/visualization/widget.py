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
Decorators (:mod:`qiskit_serverless.visualization.widget`)
===========================================================

.. currentmodule:: qiskit_serverless.visualization.widget

Qiskit Serverless widgets
==========================

.. autosummary::
    :toctree: ../stubs/

    Widget
"""
import os
from datetime import datetime

from IPython.display import display, clear_output
from ipywidgets import GridspecLayout, widgets, Layout

from qiskit_serverless.core.client import BaseClient
from qiskit_serverless.exception import QiskitServerlessException

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


class Widget:  # pylint: disable=too-many-instance-attributes
    """Widget for displaying information related to provider."""

    def __init__(self, provider: BaseClient):
        """Constructor for widget.

        Args:
            provider: provider
        """
        if provider is None:
            raise QiskitServerlessException(
                "Provider must be set in order to display widget."
            )
        self.provider = provider

        self.job_offset = 0
        self.job_limit = 10
        self.jobs = self.provider.jobs()

        self.job_list_view = widgets.Output()
        with self.job_list_view:
            display(self.render_job_list())

        self.job_pagination_view = widgets.Output()
        with self.job_pagination_view:
            display(self.render_job_pagination())

        self.program_offset = 0
        self.program_limit = 10
        self.programs = self.provider.functions()

        self.program_list_view = widgets.Output()
        with self.program_list_view:
            display(self.render_program_list())

        self.program_pagination_view = widgets.Output()
        with self.program_pagination_view:
            display(self.render_program_pagination())

        self.information_view = widgets.Output()
        with self.information_view:
            display(self.render_information())

    def render_job_list(self):
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

    def render_program_list(self):
        """Renders list of jobs."""

        def render_program_row(program):
            title = program.raw_data.get("title", "QiskitFunction")
            date = datetime.strptime(
                program.raw_data.get("created", "2011-11-11T11:11:11.000Z"),
                "%Y-%m-%dT%H:%M:%S.%fZ",
            ).strftime("%m/%d/%Y")
            return f"""
                <tr>
                    <td>{title}</td>
                    <td>{date}</td>
                </tr>
            """

        rows = "\n".join([render_program_row(program) for program in self.programs])

        table = f"""
            <table>
                {TABLE_STYLE}
                <tr>
                    <th>Title</th>
                    <th>Creation date</th>
                </tr>
                {rows}
            </table>
        """
        return widgets.HTML(table)

    def render_job_pagination(self):
        """Renders pagination."""

        def paginate(page_button):
            """Handles pagination callback logic."""
            if page_button.tooltip == "prev":
                self.jobs = self.provider.jobs(
                    limit=self.job_limit, offset=self.job_offset - self.job_limit
                )
                self.job_offset = self.job_offset - self.job_limit
            elif page_button.tooltip == "next":
                self.jobs = self.provider.jobs(
                    limit=self.job_limit, offset=self.job_offset + self.job_limit
                )
                self.job_offset = self.job_offset + self.job_limit
            with self.job_list_view:
                clear_output()
                display(self.render_job_list())
            with self.job_pagination_view:
                clear_output()
                display(self.render_job_pagination())

        prev_page = widgets.Button(
            description="Prev",
            disabled=self.job_offset < 1,
            button_style="",
            tooltip="prev",
            icon="arrow-circle-left",
        )
        prev_page.on_click(paginate)
        prev_page.layout = Layout(width="33%")

        next_page = widgets.Button(
            description="Next",
            disabled=len(self.jobs) != self.job_limit,
            button_style="",
            tooltip="next",
            icon="arrow-circle-right",
        )
        next_page.on_click(paginate)
        next_page.layout = Layout(width="33%")

        pagination_number = widgets.Button(
            description=f"{self.job_offset}-{self.job_offset + self.job_limit}",
            disabled=True,
            button_style="",
            tooltip="items",
            icon="list",
        )
        pagination_number.layout = Layout(width="33%")

        return widgets.HBox([prev_page, pagination_number, next_page])

    def render_program_pagination(self):
        """Renders pagination."""

        def paginate(page_button):
            """Handles pagination callback logic."""
            if page_button.tooltip == "prev":
                self.programs = self.provider.functions(
                    limit=self.program_limit,
                    offset=self.program_offset - self.program_limit,
                )
                self.job_offset = self.program_offset - self.job_limit
            elif page_button.tooltip == "next":
                self.jobs = self.provider.jobs(
                    limit=self.program_limit,
                    offset=self.program_offset + self.program_limit,
                )
                self.program_offset = self.program_offset + self.program_limit
            with self.program_list_view:
                clear_output()
                display(self.render_program_list())
            with self.program_pagination_view:
                clear_output()
                display(self.render_program_pagination())

        prev_page = widgets.Button(
            description="Prev",
            disabled=self.program_offset < 1,
            button_style="",
            tooltip="prev",
            icon="arrow-circle-left",
        )
        prev_page.on_click(paginate)
        prev_page.layout = Layout(width="33%")

        next_page = widgets.Button(
            description="Next",
            disabled=len(self.programs) != self.program_limit,
            button_style="",
            tooltip="next",
            icon="arrow-circle-right",
        )
        next_page.on_click(paginate)
        next_page.layout = Layout(width="33%")

        pagination_number = widgets.Button(
            description=f"{self.program_offset}-{self.program_offset + self.program_limit}",
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
            description=f"QiskitServerless [{self.provider.name}]",
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
                    <td>Client</td>
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
        job_list_widget[:9, :] = self.job_list_view
        job_list_widget[9:, 1] = self.job_pagination_view

        program_list_widget = GridspecLayout(10, 2)
        program_list_widget[:9, :] = self.program_list_view
        program_list_widget[9:, 1] = self.program_pagination_view

        tab_nest = widgets.Tab()
        tab_nest.children = [
            job_list_widget,
            program_list_widget,
            self.render_information(),
        ]
        tab_nest.set_title(0, "Jobs")
        tab_nest.set_title(1, "Functions")
        tab_nest.set_title(2, "Info")

        return tab_nest
