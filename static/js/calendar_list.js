(function () {
  const cfg = window.calendarListConfig;
  if (!cfg || !cfg.meetingCreateUrl || !cfg.eventMoveUrlTemplate) {
    return;
  }

  const meetingCreateBaseUrl = cfg.meetingCreateUrl;
  const meetingRedirectModalElement = document.getElementById("calendarMeetingRedirectModal");
  const meetingRedirectLinks = document.querySelectorAll(".js-open-meeting-create-modal");

  meetingRedirectLinks.forEach((trigger) => {
    trigger.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();

      const selectedDate = this.dataset.date || "";
      const selectedType = this.dataset.meetingType || "meeting";
      const selectedTypeLabel = selectedType === "annual_meeting" ? "Årsstämma" : "Möte";

      const params = new URLSearchParams({
        from_calendar: "1",
        date: selectedDate,
        type: selectedType,
      });
      const targetUrl = `${meetingCreateBaseUrl}?${params.toString()}`;

      if (!meetingRedirectModalElement || !window.bootstrap || !window.bootstrap.Modal) {
        window.location.href = targetUrl;
        return;
      }

      meetingRedirectModalElement.querySelector("#meetingRedirectDate").textContent = selectedDate || "—";
      meetingRedirectModalElement.querySelector("#meetingRedirectType").textContent = selectedTypeLabel;
      meetingRedirectModalElement.querySelector("#meetingRedirectContinueLink").setAttribute("href", targetUrl);

      const modal = window.bootstrap.Modal.getOrCreateInstance(meetingRedirectModalElement);
      modal.show();
    });
  });

  function getCookie(name) {
    const cookieValue = document.cookie
      .split(";")
      .map((v) => v.trim())
      .find((v) => v.startsWith(name + "="));
    return cookieValue ? decodeURIComponent(cookieValue.split("=")[1]) : null;
  }

  const csrfToken = getCookie("csrftoken");
  const modalElement = document.getElementById("calendarEventPreviewModal");
  const eventLinks = document.querySelectorAll(".js-event-preview");
  if (!eventLinks.length) return;

  let dragging = false;
  let justDropped = false;
  let draggedEventId = null;

  const dayCells = document.querySelectorAll(".calendar-day-cell[data-drop-date]");

  eventLinks.forEach((link) => {
    link.addEventListener("dragstart", function (event) {
      dragging = true;
      justDropped = false;
      draggedEventId = this.dataset.eventId;
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", draggedEventId || "");
    });

    link.addEventListener("dragend", function () {
      setTimeout(() => {
        dragging = false;
        draggedEventId = null;
      }, 0);
    });

    link.addEventListener("click", function (event) {
      if (justDropped || dragging) {
        justDropped = false;
        event.preventDefault();
        event.stopPropagation();
        return;
      }

      if (!modalElement || !window.bootstrap || !window.bootstrap.Modal) {
        return;
      }

      event.preventDefault();
      event.stopPropagation();

      modalElement.querySelector("#calendarEventPreviewModalLabel").textContent = this.dataset.eventTitle || "Händelse";
      modalElement.querySelector("#eventPreviewType").textContent = this.dataset.eventType || "—";
      modalElement.querySelector("#eventPreviewStart").textContent = this.dataset.eventStart || "—";
      modalElement.querySelector("#eventPreviewEnd").textContent = this.dataset.eventEnd || "—";
      modalElement.querySelector("#eventPreviewLocation").textContent = this.dataset.eventLocation || "—";
      modalElement.querySelector("#eventPreviewDescription").textContent = this.dataset.eventDescription || "—";
      modalElement.querySelector("#eventPreviewDetailLink").setAttribute("href", this.dataset.eventDetailUrl || this.getAttribute("href"));

      const modal = window.bootstrap.Modal.getOrCreateInstance(modalElement);
      modal.show();
    });
  });

  dayCells.forEach((cell) => {
    cell.addEventListener("dragover", function (event) {
      if (!draggedEventId) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
    });

    cell.addEventListener("drop", function (event) {
      if (!draggedEventId) return;
      event.preventDefault();
      event.stopPropagation();

      const targetDate = this.dataset.dropDate;
      if (!targetDate) return;

      // Placeholder 888888888 must match {% url 'calendarapp:move' 888888888 %} in calendar_list.html
      const moveUrl = cfg.eventMoveUrlTemplate.replace("888888888", String(draggedEventId));

      fetch(moveUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken || "",
        },
        body: JSON.stringify({ target_date: targetDate }),
      })
        .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
        .then(({ ok, data }) => {
          if (!ok || !data.ok) {
            alert("Kunde inte flytta händelsen.");
            return;
          }
          justDropped = true;
          window.location.reload();
        })
        .catch(() => {
          alert("Kunde inte flytta händelsen.");
        });
    });
  });
})();
