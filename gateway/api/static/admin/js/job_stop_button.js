// Behaviour of the Job admin "Stop job" button.
//
// This file exists because the project's Content Security Policy forbids inline event handler
// attributes (script-src is 'none' and there is no script-src-attr override), so the button
// can't carry an onclick attribute: the URL travels in a data-stop-url attribute instead, and
// this listens for the click.

(function () {
    const button = document.querySelector(".qs-stop-job-btn");
    if (!button) return;

    button.addEventListener("click", function () {
        if (
            !confirm(
                "Stop this job? This only marks it as STOPPED in the database, it does not cancel anything running on Ray."
            )
        ) {
            return;
        }
        if (!confirm("Are you sure? This cannot be undone.")) return;

        const match = document.cookie.match(/csrftoken=([^;]+)/);
        fetch(button.dataset.stopUrl, {
            method: "POST",
            headers: { "X-CSRFToken": match ? match[1] : "" },
        }).then(function () {
            location.reload();
        });
    });
})();
