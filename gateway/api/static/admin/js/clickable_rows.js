document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("#result_list tbody tr").forEach(function (row) {
        const link = row.querySelector("th a, td a");
        if (!link) return;
        row.addEventListener("click", function (e) {
            if (e.target.closest("a, input, button")) return;
            window.location = link.href;
        });
    });
});
