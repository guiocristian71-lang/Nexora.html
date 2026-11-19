(() => {
  const toggle = document.querySelector("[data-sidebar-toggle]");
  const close = document.querySelector("[data-sidebar-close]");
  if (!toggle) return;

  const mobileQuery = window.matchMedia("(max-width: 760px)");
  try {
    if (localStorage.getItem("gestor-sidebar-collapsed") === "true") {
      document.body.classList.add("sidebar-collapsed");
      toggle.setAttribute("aria-expanded", "false");
      toggle.setAttribute("aria-label", "Expandir menú");
    }
  } catch {
    // The menu remains usable when browser storage is disabled.
  }

  const setMobileMenu = (open) => {
    document.body.classList.toggle("mobile-menu-open", open);
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-label", open ? "Cerrar menú" : "Abrir menú");
    if (!open) toggle.focus();
  };

  toggle.addEventListener("click", () => {
    if (mobileQuery.matches) {
      setMobileMenu(!document.body.classList.contains("mobile-menu-open"));
      return;
    }
    const collapsed = document.body.classList.toggle("sidebar-collapsed");
    toggle.setAttribute("aria-expanded", String(!collapsed));
    toggle.setAttribute("aria-label", collapsed ? "Expandir menú" : "Contraer menú");
    try {
      localStorage.setItem("gestor-sidebar-collapsed", String(collapsed));
    } catch {
      // Collapsing still works for the current page when storage is disabled.
    }
  });

  close?.addEventListener("click", () => setMobileMenu(false));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && document.body.classList.contains("mobile-menu-open")) {
      setMobileMenu(false);
    }
  });
  mobileQuery.addEventListener("change", () => {
    document.body.classList.remove("mobile-menu-open");
    if (mobileQuery.matches) {
      toggle.setAttribute("aria-expanded", "false");
      toggle.setAttribute("aria-label", "Abrir menú");
      return;
    }
    const collapsed = document.body.classList.contains("sidebar-collapsed");
    toggle.setAttribute("aria-expanded", String(!collapsed));
    toggle.setAttribute("aria-label", collapsed ? "Expandir menú" : "Contraer menú");
  });
})();

const notificationToggle = document.querySelector("[data-notification-toggle]");
const notificationPopover = document.querySelector("[data-notification-popover]");

if (notificationToggle && notificationPopover) {
  notificationToggle.addEventListener("click", (event) => {
    event.stopPropagation();
    const open = notificationPopover.classList.toggle("is-open");
    notificationToggle.setAttribute("aria-expanded", String(open));
  });

  document.addEventListener("click", (event) => {
    if (!notificationPopover.contains(event.target) && event.target !== notificationToggle) {
      notificationPopover.classList.remove("is-open");
      notificationToggle.setAttribute("aria-expanded", "false");
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      notificationPopover.classList.remove("is-open");
      notificationToggle.setAttribute("aria-expanded", "false");
    }
  });
}

document.querySelectorAll("[data-date-picker]").forEach((picker) => {
  const dateValue = picker.querySelector("[data-date-value]");
  const dateDisplay = picker.querySelector("[data-date-display]");
  const toggle = picker.querySelector("[data-calendar-toggle]");
  const calendar = picker.querySelector("[data-calendar]");
  const monthLabel = picker.querySelector("[data-calendar-month]");
  const daysContainer = picker.querySelector("[data-calendar-days]");
  const previous = picker.querySelector("[data-calendar-previous]");
  const next = picker.querySelector("[data-calendar-next]");
  const dateError = picker.parentElement.querySelector("[data-date-error]");
  const form = picker.closest("form");
  if (!dateValue || !dateDisplay || !toggle || !calendar || !monthLabel || !daysContainer || !previous || !next || !dateError || !form) return;

  const weekdays = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];
  const monthFormatter = new Intl.DateTimeFormat("es", { month: "long", year: "numeric" });
  const now = new Date();
  const todayISO = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  let visibleMonth = new Date();
  const selectedDate = dateValue.value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  const showInvalidDate = () => {
    dateValue.value = "";
    dateDisplay.value = "Fecha inválida";
    dateDisplay.setAttribute("aria-invalid", "true");
    dateError.textContent = "Fecha inválida.";
    dateError.hidden = false;
  };
  const clearDateError = () => {
    dateDisplay.removeAttribute("aria-invalid");
    dateError.textContent = "Selecciona una fecha de registro.";
    dateError.hidden = true;
  };
  if (selectedDate) {
    visibleMonth = new Date(Number(selectedDate[1]), Number(selectedDate[2]) - 1, 1);
    if (dateValue.value > todayISO) {
      showInvalidDate();
    } else {
      dateDisplay.value = `${selectedDate[3]}/${selectedDate[2]}/${selectedDate[1]}`;
    }
  } else {
    visibleMonth = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth(), 1);
  }

  const renderCalendar = () => {
    const year = visibleMonth.getFullYear();
    const month = visibleMonth.getMonth();
    monthLabel.textContent = monthFormatter.format(visibleMonth);
    daysContainer.replaceChildren();

    const firstWeekday = (new Date(year, month, 1).getDay() + 6) % 7;
    for (let blank = 0; blank < firstWeekday; blank += 1) {
      const spacer = document.createElement("span");
      spacer.className = "date-picker-spacer";
      spacer.setAttribute("aria-hidden", "true");
      daysContainer.append(spacer);
    }

    const daysInMonth = new Date(year, month + 1, 0).getDate();
    for (let day = 1; day <= daysInMonth; day += 1) {
      const button = document.createElement("button");
      const isoDate = `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
      const fullDate = new Date(year, month, day);
      button.type = "button";
      button.textContent = String(day);
      button.setAttribute("role", "gridcell");
      button.setAttribute("aria-label", `${weekdays[fullDate.getDay()]} ${day}`);
      if (dateValue.value === isoDate) button.setAttribute("aria-selected", "true");
      button.addEventListener("click", () => {
        if (isoDate > todayISO) {
          showInvalidDate();
          calendar.hidden = true;
          toggle.setAttribute("aria-expanded", "false");
          toggle.focus();
          return;
        }
        dateValue.value = isoDate;
        dateDisplay.value = `${String(day).padStart(2, "0")}/${String(month + 1).padStart(2, "0")}/${year}`;
        clearDateError();
        calendar.hidden = true;
        toggle.setAttribute("aria-expanded", "false");
        toggle.focus();
      });
      daysContainer.append(button);
    }
  };

  toggle.addEventListener("click", () => {
    const open = calendar.hidden;
    calendar.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    if (open) renderCalendar();
  });
  previous.addEventListener("click", () => {
    visibleMonth = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() - 1, 1);
    renderCalendar();
  });
  next.addEventListener("click", () => {
    visibleMonth = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() + 1, 1);
    renderCalendar();
  });
  form.addEventListener("submit", (event) => {
    if (!dateValue.value) {
      event.preventDefault();
      dateDisplay.setAttribute("aria-invalid", "true");
      if (dateDisplay.value !== "Fecha inválida") {
        dateError.textContent = "Selecciona una fecha de registro.";
        dateError.hidden = false;
      }
      dateDisplay.focus();
    }
  });
  document.addEventListener("click", (event) => {
    if (!picker.contains(event.target)) {
      calendar.hidden = true;
      toggle.setAttribute("aria-expanded", "false");
    }
  });
  picker.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      calendar.hidden = true;
      toggle.setAttribute("aria-expanded", "false");
      toggle.focus();
    }
  });
});

const maintenanceForm = document.querySelector("[data-maintenance-form]");
if (maintenanceForm) {
  const equipmentSelect = maintenanceForm.querySelector("[data-maintenance-equipment]");
  const reviewDate = maintenanceForm.querySelector("[data-maintenance-review-date]");
  const dependentFields = maintenanceForm.querySelectorAll("[data-maintenance-dependent]");
  const inactiveEquipmentError = maintenanceForm.querySelector("[data-inactive-equipment-error]");
  const nextMaintenanceDate = maintenanceForm.querySelector("[data-next-maintenance]");
  const nextMaintenanceError = maintenanceForm.querySelector("[data-next-maintenance-error]");

  if (equipmentSelect) {
    const updateEquipmentAvailability = () => {
      const selectedOption = equipmentSelect.selectedOptions[0];
      const inactive =
        Boolean(equipmentSelect.value) &&
        selectedOption.dataset.equipmentStatus?.trim().toLowerCase() === "inactivo";

      if (reviewDate) {
        if (inactive) {
          reviewDate.value = "Fecha inválida";
          reviewDate.setAttribute("aria-invalid", "true");
        } else {
          const now = new Date();
          const fallbackDate = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
          reviewDate.value = equipmentSelect.value
            ? selectedOption.dataset.registrationDate || fallbackDate
            : "";
          reviewDate.removeAttribute("aria-invalid");
        }
      }

      dependentFields.forEach((field) => {
        field.disabled = inactive;
      });
      if (inactiveEquipmentError) inactiveEquipmentError.hidden = !inactive;
    };

    equipmentSelect.addEventListener("change", updateEquipmentAvailability);
    updateEquipmentAvailability();
  }

  if (nextMaintenanceDate && nextMaintenanceError) {
    const now = new Date();
    const todayISO = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
    const validateNextMaintenanceDate = () => {
      const invalid = Boolean(nextMaintenanceDate.value) && nextMaintenanceDate.value <= todayISO;
      if (invalid) {
        nextMaintenanceDate.setAttribute("aria-invalid", "true");
        nextMaintenanceDate.setCustomValidity("Fecha inválida.");
        nextMaintenanceError.hidden = false;
      } else {
        nextMaintenanceDate.removeAttribute("aria-invalid");
        nextMaintenanceDate.setCustomValidity("");
        nextMaintenanceError.hidden = true;
      }
      return invalid;
    };

    nextMaintenanceDate.addEventListener("change", validateNextMaintenanceDate);
    nextMaintenanceDate.addEventListener("input", validateNextMaintenanceDate);
    maintenanceForm.addEventListener("submit", (event) => {
      if (validateNextMaintenanceDate()) {
        event.preventDefault();
        nextMaintenanceDate.reportValidity();
      }
    });
    validateNextMaintenanceDate();
  }
}

const deleteConfirmDialog = document.querySelector("[data-delete-confirm-dialog]");
if (deleteConfirmDialog) {
  const cancelButton = deleteConfirmDialog.querySelector("[data-delete-cancel]");
  const acceptButton = deleteConfirmDialog.querySelector("[data-delete-accept]");
  let pendingDeleteForm = null;

  document.querySelectorAll("form[data-confirm-delete]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (form.dataset.confirmed === "true") {
        delete form.dataset.confirmed;
        return;
      }
      event.preventDefault();
      pendingDeleteForm = form;
      deleteConfirmDialog.showModal();
    });
  });

  cancelButton?.addEventListener("click", () => deleteConfirmDialog.close());
  acceptButton?.addEventListener("click", () => {
    if (!pendingDeleteForm) return;
    const form = pendingDeleteForm;
    pendingDeleteForm = null;
    form.dataset.confirmed = "true";
    deleteConfirmDialog.close();
    form.requestSubmit();
  });
  deleteConfirmDialog.addEventListener("close", () => {
    pendingDeleteForm = null;
  });
}

const equipmentSearchInput = document.querySelector("[data-spanish-autocorrect]");
if (equipmentSearchInput) {
  const accentCorrections = new Map([
    ["area", "área"],
    ["bogota", "bogotá"],
    ["bateria", "batería"],
    ["camara", "cámara"],
    ["codigo", "código"],
    ["descripcion", "descripción"],
    ["dia", "día"],
    ["diseno", "diseño"],
    ["electronico", "electrónico"],
    ["electrico", "eléctrico"],
    ["energia", "energía"],
    ["garcia", "garcía"],
    ["garantia", "garantía"],
    ["grafico", "gráfico"],
    ["hernandez", "hernández"],
    ["gomez", "gómez"],
    ["gonzalez", "gonzález"],
    ["jose", "josé"],
    ["julian", "julián"],
    ["medellin", "medellín"],
    ["mecanico", "mecánico"],
    ["maria", "maría"],
    ["numero", "número"],
    ["oscar", "óscar"],
    ["perez", "pérez"],
    ["pinzon", "pinzón"],
    ["raul", "raúl"],
    ["reparacion", "reparación"],
    ["revision", "revisión"],
    ["tecnico", "técnico"],
    ["telefono", "teléfono"],
    ["tecnologia", "tecnología"],
    ["ultimo", "último"],
    ["angel", "ángel"],
    ["andres", "andrés"],
    ["hector", "héctor"],
    ["ivan", "iván"],
  ]);
  equipmentSearchInput.addEventListener("input", () => {
    const cursorPosition = equipmentSearchInput.selectionStart;
    const correctedValue = equipmentSearchInput.value.replace(
      /[a-záéíóúüñ]+/gi,
      (word) => {
        const corrected = accentCorrections.get(word.toLocaleLowerCase("es"));
        if (!corrected) return word;
        if (word === word.toLocaleUpperCase("es")) {
          return corrected.toLocaleUpperCase("es");
        }
        if (word[0] === word[0].toLocaleUpperCase("es")) {
          return corrected[0].toLocaleUpperCase("es") + corrected.slice(1);
        }
        return corrected;
      },
    );
    if (correctedValue !== equipmentSearchInput.value) {
      equipmentSearchInput.value = correctedValue;
      equipmentSearchInput.setSelectionRange(cursorPosition, cursorPosition);
    }
  });
}

const clearEquipmentSearch = document.querySelector("[data-clear-equipment-search]");
if (equipmentSearchInput && clearEquipmentSearch) {
  clearEquipmentSearch.addEventListener("click", () => {
    equipmentSearchInput.value = "";
    equipmentSearchInput.form?.requestSubmit();
  });
}
