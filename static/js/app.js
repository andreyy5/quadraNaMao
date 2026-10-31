(function () {
  const TOAST_KEY = "qnm-toast";
  const MODE_KEY = "qnm-mode";
  const TAB_KEY = "qnm-agenda-tab";
  let lastToast = null;

  function readCookie(name) {
    const match = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return match ? decodeURIComponent(match[1]) : "";
  }

  document.addEventListener("htmx:configRequest", (event) => {
    event.detail.headers["X-CSRFToken"] = readCookie("csrftoken");
  });

  /* Painel */
  function modal() {
    return document.getElementById("modal");
  }

  function closeModal() {
    const dialog = modal();
    if (!dialog) return;
    if (dialog.open) dialog.close();
    document.getElementById("modal-body").innerHTML = "";
  }

  document.addEventListener("htmx:afterSwap", (event) => {
    if (event.detail.target.id !== "modal-body") return;
    const dialog = modal();
    if (!dialog.open) dialog.showModal();
    dialog.scrollTop = 0;
    // No celular o foco automático abriria o teclado por cima do painel.
    const focus = dialog.querySelector("[data-autofocus]");
    if (focus && !focus.value && window.matchMedia("(min-width: 768px)").matches) focus.focus();
  });

  document.addEventListener("modal:close", closeModal);

  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-close-modal]")) {
      if (modal().contains(event.target)) closeModal();
      else history.back();
      return;
    }
    if (event.target === modal()) closeModal();
  });

  /* Avisos */
  function dismissLater(element) {
    setTimeout(() => element.remove(), 4500);
  }

  function showToast(message) {
    const host = document.getElementById("toasts");
    if (!host) return;
    const toast = document.createElement("div");
    toast.className = "card px-4 py-3 text-sm shadow-card";
    toast.setAttribute("role", "status");
    toast.textContent = message;
    host.appendChild(toast);
    dismissLater(toast);
  }

  function initPage() {
    document.querySelectorAll("[data-toast]").forEach(dismissLater);
    const pending = sessionStorage.getItem(TOAST_KEY);
    if (pending) {
      sessionStorage.removeItem(TOAST_KEY);
      showToast(pending);
    }
    const now = Array.from(document.querySelectorAll("[data-now]")).find((el) => el.offsetParent !== null);
    if (now && now.getBoundingClientRect().bottom > window.innerHeight - 120) now.scrollIntoView({ block: "center" });
  }

  document.addEventListener("toast", (event) => {
    lastToast = event.detail.message;
    showToast(lastToast);
  });

  /* Depois de uma alteração, atualiza a agenda na tela ou recarrega a página. */
  document.addEventListener("data:changed", () => {
    const target = document.querySelector("[data-refresh]");
    if (target) {
      window.htmx.trigger(target, "refresh");
      return;
    }
    if (lastToast) sessionStorage.setItem(TOAST_KEY, lastToast);
    location.reload();
  });

  document.addEventListener("DOMContentLoaded", initPage);
  document.addEventListener("htmx:afterSettle", (event) => {
    if (event.detail.boosted) initPage();
  });

  /* Componentes Alpine */
  document.addEventListener("alpine:init", () => {
    const Alpine = window.Alpine;

    Alpine.data("themeToggle", () => ({
      mode: document.documentElement.dataset.mode || "dark",
      toggle() {
        this.mode = this.mode === "dark" ? "light" : "dark";
        document.documentElement.dataset.mode = this.mode;
        localStorage.setItem(MODE_KEY, this.mode);
      },
    }));

    Alpine.data("agendaTabs", (ids) => ({
      ids,
      active: ids[0],
      init() {
        const saved = Number(sessionStorage.getItem(TAB_KEY));
        if (ids.includes(saved)) this.active = saved;
      },
      select(id) {
        this.active = id;
        sessionStorage.setItem(TAB_KEY, id);
      },
    }));

    Alpine.data("reservaForm", (data) => ({
      clienteId: data.cliente || "",
      nome: data.nome || "",
      telefone: data.telefone || "",
      pick(option) {
        this.clienteId = option.id;
        this.nome = option.nome;
        this.telefone = option.telefone;
        this.clearResults();
      },
      clearResults() {
        this.$refs.results.innerHTML = "";
      },
    }));

    Alpine.data("weekHours", () => ({
      copyFirst() {
        const rows = Array.from(this.$root.querySelectorAll("[data-hours-row]"));
        const [first, ...others] = rows;
        const value = (row, name) => row.querySelector(`[name$="-${name}"]`);
        others.forEach((row) => {
          value(row, "aberto").checked = value(first, "aberto").checked;
          value(row, "abre").value = value(first, "abre").value;
          value(row, "fecha").value = value(first, "fecha").value;
        });
      },
    }));
  });
})();
