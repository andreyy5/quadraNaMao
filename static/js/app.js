(function () {
  const TOAST_KEY = "qnm-toast";
  const MODE_KEY = "qnm-mode";
  const TAB_KEY = "qnm-agenda-tab";
  const CHECK_ICON =
    '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12.500 4.500 4.500L19 7.500"/></svg>';
  let lastToast = null;

  function readCookie(name) {
    const match = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return match ? decodeURIComponent(match[1]) : "";
  }

  function isVisible(element) {
    return element.getClientRects().length > 0;
  }

  function clickVisible(selector) {
    const element = Array.from(document.querySelectorAll(selector)).find(isVisible);
    if (element) element.click();
  }

  document.addEventListener("htmx:configRequest", (event) => {
    event.detail.headers["X-CSRFToken"] = readCookie("csrftoken");
  });

  /* Barra de progresso: a atualização periódica da agenda não conta, e respostas rápidas nem chegam a aparecer. */
  let pending = 0;
  let progressTimer = null;

  function progress() {
    return document.getElementById("progress");
  }

  document.addEventListener("htmx:beforeRequest", (event) => {
    if (event.detail.elt.id === "agenda-grid") return;
    pending += 1;
    if (pending > 1 || !progress()) return;
    clearTimeout(progressTimer);
    progressTimer = setTimeout(() => {
      progress().classList.remove("is-done");
      progress().classList.add("is-active");
    }, 120);
  });

  document.addEventListener("htmx:afterRequest", (event) => {
    if (event.detail.elt.id === "agenda-grid") return;
    pending = Math.max(0, pending - 1);
    if (pending) return;
    clearTimeout(progressTimer);
    const bar = progress();
    if (bar && bar.classList.contains("is-active")) {
      bar.classList.remove("is-active");
      bar.classList.add("is-done");
    }
  });

  /* Painel */
  let closeTimer = null;

  function modal() {
    return document.getElementById("modal");
  }

  function closeModal() {
    const dialog = modal();
    if (!dialog || !dialog.open) return;
    dialog.classList.add("is-closing");
    closeTimer = setTimeout(() => {
      dialog.classList.remove("is-closing");
      dialog.close();
      document.getElementById("modal-body").innerHTML = "";
    }, 140);
  }

  document.addEventListener("htmx:afterSwap", (event) => {
    if (event.detail.target.id !== "modal-body") return;
    clearTimeout(closeTimer);
    const dialog = modal();
    dialog.classList.remove("is-closing");
    if (!dialog.open) dialog.showModal();
    dialog.scrollTop = 0;
    // No celular o foco automático abriria o teclado por cima do painel; a busca é a exceção.
    const focus = dialog.querySelector("[data-autofocus]");
    const wide = window.matchMedia("(min-width: 768px)").matches;
    if (focus && !focus.value && (wide || focus.dataset.autofocus === "always")) focus.focus();
    else dialog.focus({ preventScroll: true });
    selectPaletteItem(0);
  });

  document.addEventListener("modal:close", closeModal);

  document.addEventListener(
    "cancel",
    (event) => {
      if (event.target !== modal()) return;
      event.preventDefault();
      closeModal();
    },
    true
  );

  document.addEventListener("click", (event) => {
    const leaving = event.target.closest("[data-toast], .toast");
    if (leaving) dismiss(leaving);
    if (event.target.closest("[data-close-modal]")) {
      if (modal().contains(event.target)) closeModal();
      else history.back();
      return;
    }
    if (event.target === modal()) closeModal();
  });

  /* Busca rápida */
  let paletteIndex = 0;

  function paletteItems() {
    return Array.from(document.querySelectorAll("#palette-results [data-palette-item]"));
  }

  function selectPaletteItem(index) {
    const items = paletteItems();
    if (!items.length) return;
    paletteIndex = (index + items.length) % items.length;
    items.forEach((item, position) => item.classList.toggle("is-selected", position === paletteIndex));
    items[paletteIndex].scrollIntoView({ block: "nearest" });
  }

  /* Atalhos de teclado */
  function isTyping(element) {
    return element.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(element.tagName);
  }

  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      if (!document.querySelector("[data-palette]")) clickVisible("[data-palette-open]");
      return;
    }
    if (document.querySelector("#modal [data-palette]")) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        selectPaletteItem(paletteIndex + (event.key === "ArrowDown" ? 1 : -1));
      } else if (event.key === "Enter") {
        event.preventDefault();
        const item = paletteItems()[paletteIndex];
        if (item) item.click();
      }
      return;
    }
    if (event.ctrlKey || event.metaKey || event.altKey || isTyping(event.target)) return;
    if (modal() && modal().open) return;
    const shortcuts = {
      n: "[data-new-reserva]",
      b: "[data-new-bloqueio]",
      t: "[data-agenda-today]",
      ArrowLeft: "[data-agenda-previous]",
      ArrowRight: "[data-agenda-next]",
      "/": "[data-palette-open]",
    };
    const selector = shortcuts[event.key];
    if (!selector) return;
    event.preventDefault();
    clickVisible(selector);
  });

  /* Avisos */
  function dismiss(element) {
    if (element.classList.contains("is-leaving")) return;
    element.classList.add("is-leaving");
    setTimeout(() => element.remove(), 200);
  }

  function dismissLater(element) {
    setTimeout(() => dismiss(element), 4500);
  }

  function showToast(message) {
    const host = document.getElementById("toasts");
    if (!host) return;
    const toast = document.createElement("div");
    toast.className = "toast pointer-events-auto";
    toast.setAttribute("role", "status");
    toast.innerHTML = CHECK_ICON;
    const text = document.createElement("span");
    text.textContent = message;
    toast.appendChild(text);
    host.appendChild(toast);
    dismissLater(toast);
  }

  /* Contagem até o próximo jogo */
  function updateCountdowns() {
    document.querySelectorAll("[data-countdown]").forEach((element) => {
      const minutes = Math.ceil((new Date(element.dataset.countdown) - Date.now()) / 60000);
      if (minutes <= 0) {
        element.textContent = "agora";
      } else if (minutes < 60) {
        element.textContent = `em ${minutes} min`;
      } else {
        const rest = minutes % 60;
        element.textContent = `em ${Math.floor(minutes / 60)}h${rest ? ` ${rest}min` : ""}`;
      }
    });
  }

  setInterval(updateCountdowns, 30000);

  /* Na agenda de tela grande a grade rola por dentro: abre com a hora atual à vista. */
  function revealNow() {
    const now = Array.from(document.querySelectorAll("[data-now]")).find(isVisible);
    if (!now) return;
    const scroller = now.closest("[data-scroll]");
    if (scroller && getComputedStyle(scroller).maxHeight !== "none") {
      scroller.scrollTop = Math.max(0, now.offsetTop - scroller.clientHeight / 3);
    } else if (now.getBoundingClientRect().bottom > window.innerHeight - 120) {
      now.scrollIntoView({ block: "center" });
    }
  }

  function initPage() {
    document.querySelectorAll("[data-toast]").forEach(dismissLater);
    const queued = sessionStorage.getItem(TOAST_KEY);
    if (queued) {
      sessionStorage.removeItem(TOAST_KEY);
      showToast(queued);
    }
    updateCountdowns();
    revealNow();
  }

  document.addEventListener("toast", (event) => {
    lastToast = event.detail.message;
    showToast(lastToast);
  });

  /* A atualização da agenda troca a grade inteira: a rolagem precisa continuar onde estava. */
  let gridScroll = null;

  document.addEventListener("htmx:beforeSwap", (event) => {
    if (event.detail.target.id !== "agenda-grid") return;
    const scroller = event.detail.target.querySelector("[data-scroll]");
    if (scroller) gridScroll = { top: scroller.scrollTop, left: scroller.scrollLeft };
  });

  function restoreGridScroll() {
    if (!gridScroll) return;
    const scroller = document.querySelector("#agenda-grid [data-scroll]");
    if (scroller) {
      scroller.scrollTop = gridScroll.top;
      scroller.scrollLeft = gridScroll.left;
    }
    gridScroll = null;
  }

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
    restoreGridScroll();
    if (event.detail.boosted) initPage();
    if (!paletteItems().some((item) => item.classList.contains("is-selected"))) selectPaletteItem(0);
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

    Alpine.data("datePicker", () => ({
      open() {
        const input = this.$refs.date;
        if (input.showPicker) input.showPicker();
        else input.focus();
      },
      go() {
        if (!this.$refs.date.value) return;
        const url = new URL(this.$refs.date.dataset.url, location.href);
        url.searchParams.set("data", this.$refs.date.value);
        location.href = url;
      },
    }));

    Alpine.data("reservaForm", (data) => ({
      clienteId: data.cliente || "",
      nome: data.nome || "",
      telefone: data.telefone || "",
      resumo: { espaco: "", dia: "", horario: "" },
      init() {
        this.refreshSummary();
      },
      pick(option) {
        this.clienteId = option.id;
        this.nome = option.nome;
        this.telefone = option.telefone;
        this.clearResults();
      },
      clearResults() {
        this.$refs.results.innerHTML = "";
      },
      refreshSummary() {
        const field = (name) => this.$root.querySelector(`[name="${name}"]`);
        const espaco = field("espaco");
        const dia = field("data").value;
        const hora = field("hora").value;
        const minutos = Number(field("duracao").value);
        this.resumo.espaco = espaco.selectedOptions[0] ? espaco.selectedOptions[0].text : "";
        this.resumo.dia = "";
        this.resumo.horario = "";
        if (dia) {
          const [year, month, day] = dia.split("-").map(Number);
          this.resumo.dia = new Date(year, month - 1, day).toLocaleDateString("pt-BR", {
            weekday: "short",
            day: "2-digit",
            month: "2-digit",
          });
        }
        if (hora && minutos) {
          const [hours, mins] = hora.split(":").map(Number);
          const end = hours * 60 + mins + minutos;
          const pad = (value) => String(value).padStart(2, "0");
          this.resumo.horario = `${hora}–${pad(Math.floor(end / 60) % 24)}:${pad(end % 60)}`;
        }
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
