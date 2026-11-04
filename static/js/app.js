(function () {
  const TOAST_KEY = "qnm-toast";
  const MODE_KEY = "qnm-mode";
  const TAB_KEY = "qnm-agenda-tab";
  const CART_KEY = "qnm-pdv-cart";
  const CHECK_ICON =
    '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12.500 4.500 4.500L19 7.500"/></svg>';
  const ALERT_ICON =
    '<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4 2.800 20h18.400L12 4Z"/><path d="M12 10v4.500M12 17.500v.01"/></svg>';
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

  /* Telefone formatado enquanto digita. Em captura, para o x-model já receber o valor formatado. */
  function formatPhone(raw) {
    const digits = raw.replace(/\D/g, "").slice(0, 11);
    if (!digits) return "";
    if (digits.length <= 2) return `(${digits}`;
    const area = `(${digits.slice(0, 2)}) `;
    const rest = digits.slice(2);
    if (rest.length <= 4) return area + rest;
    const split = rest.length === 9 ? 5 : 4;
    return `${area}${rest.slice(0, split)}-${rest.slice(split)}`;
  }

  document.addEventListener(
    "input",
    (event) => {
      const input = event.target;
      if (input.dataset.mask !== "phone" || input.value.startsWith("+")) return;
      if (input.selectionStart === input.value.length) input.value = formatPhone(input.value);
    },
    true
  );

  function initials(name) {
    const parts = (name || "").trim().split(/\s+/).filter(Boolean);
    return parts.length ? (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase() : "";
  }

  function shortDate(iso) {
    if (!iso) return "";
    const [year, month, day] = iso.split("-").map(Number);
    return new Date(year, month - 1, day).toLocaleDateString("pt-BR", {
      weekday: "short",
      day: "2-digit",
      month: "2-digit",
    });
  }

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

  function showToast(message, level) {
    const host = document.getElementById("toasts");
    if (!host) return;
    const toast = document.createElement("div");
    toast.className = `toast pointer-events-auto ${level === "error" ? "toast-error" : ""}`;
    toast.setAttribute("role", level === "error" ? "alert" : "status");
    toast.innerHTML = level === "error" ? ALERT_ICON : CHECK_ICON;
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
      const { message, level } = JSON.parse(queued);
      showToast(message, level);
    }
    updateCountdowns();
    revealNow();
  }

  document.addEventListener("toast", (event) => {
    lastToast = { message: event.detail.message, level: event.detail.level };
    showToast(lastToast.message, lastToast.level);
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
    if (lastToast) sessionStorage.setItem(TOAST_KEY, JSON.stringify(lastToast));
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

    Alpine.magic("initials", () => initials);

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

    Alpine.data("dayPicker", () => ({
      days: [],
      selected: "",
      init() {
        this.input = this.$el.querySelector('input[type="date"]');
        this.selected = this.input.value;
        this.input.addEventListener("change", () => {
          this.selected = this.input.value;
          this.build();
        });
        this.build();
      },
      build() {
        const toIso = (date) =>
          `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
        const today = new Date();
        const todayIso = toIso(today);
        const dates = Array.from({ length: 14 }, (_, offset) => new Date(today.getFullYear(), today.getMonth(), today.getDate() + offset));
        // Uma data fora das próximas duas semanas, como ao remarcar, continua à vista.
        if (this.selected && !dates.some((date) => toIso(date) === this.selected)) {
          const [year, month, day] = this.selected.split("-").map(Number);
          const extra = new Date(year, month - 1, day);
          if (extra < today) dates.unshift(extra);
          else dates.push(extra);
        }
        this.days = dates.map((date) => ({
          iso: toIso(date),
          isToday: toIso(date) === todayIso,
          weekday: date.toLocaleDateString("pt-BR", { weekday: "short" }).replace(".", ""),
          day: String(date.getDate()).padStart(2, "0"),
          label: date.toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long" }),
        }));
        this.$nextTick(() => this.center());
      },
      center() {
        const scroller = this.$refs.scroller;
        const pill = scroller && scroller.querySelector(".is-selected");
        if (pill) scroller.scrollLeft = pill.offsetLeft - scroller.offsetLeft - scroller.clientWidth / 2 + pill.offsetWidth / 2;
      },
      pick(iso) {
        this.input.value = iso;
        this.input.dispatchEvent(new Event("change", { bubbles: true }));
      },
      openCalendar() {
        if (this.input.showPicker) this.input.showPicker();
        else this.input.focus();
      },
    }));

    Alpine.data("reservaForm", (data) => ({
      clienteId: data.cliente || "",
      nome: data.nome || "",
      telefone: data.telefone || "",
      editing: data.editing !== "false",
      tema: "",
      modalidade: "",
      autoOk: false,
      resumo: { espaco: "", dia: "", horario: "", valor: "" },
      init() {
        this.form = this.$el;
        this.readModalidade();
        this.refreshSummary();
      },
      readModalidade() {
        const checked = this.form.querySelector('[name="modalidade"]:checked');
        this.modalidade = checked ? checked.value : "";
        this.autoOk = checked ? Number(checked.closest("label").dataset.count) > 1 : false;
      },
      fits(card) {
        // Sem a escolha de modalidade na tela, todos os espaços aparecem.
        if (!this.form.querySelector('[name="modalidade"]')) return true;
        return card.dataset.modalidades.split(" ").includes(this.modalidade);
      },
      onModalidade(event) {
        if (event.target.name !== "modalidade") return;
        this.readModalidade();
        // Roda antes de o evento chegar ao HTMX: a consulta de horários já sai com o espaço certo.
        const auto = this.form.querySelector('[data-auto] input');
        const own = Array.from(this.form.querySelectorAll("[data-modalidades]")).filter((card) =>
          card.dataset.modalidades.split(" ").includes(this.modalidade),
        );
        const target = this.autoOk ? auto : own[0] && own[0].querySelector("input");
        if (target) target.checked = true;
      },
      pick(option) {
        this.clienteId = option.id;
        this.nome = option.nome;
        this.telefone = option.telefone;
        this.clearResults();
      },
      clearClient() {
        this.clienteId = "";
        this.nome = "";
        this.telefone = "";
      },
      clearResults() {
        this.$refs.results.innerHTML = "";
      },
      pickTime(hora) {
        const input = this.form.querySelector('[name="hora"]');
        input.value = hora;
        input.dispatchEvent(new Event("change", { bubbles: true }));
      },
      refreshSummary() {
        const field = (selector) => this.form.querySelector(selector);
        const espaco = field('[name="espaco"]:checked');
        const modalidade = field('[name="modalidade"]:checked');
        const duracao = field('[name="duracao"]:checked');
        const hora = field('[name="hora"]').value;
        const valor = field('[name="valor_total"]');
        const auto = espaco && !espaco.value;
        const source = auto ? modalidade : espaco;
        this.tema = source ? source.closest("label").dataset.theme || "" : "";
        if (auto) {
          this.resumo.espaco = modalidade ? `${modalidade.closest("label").innerText.trim()} · automático` : "Automático";
        } else {
          this.resumo.espaco = espaco ? espaco.closest("label").innerText.trim() : "";
        }
        this.resumo.dia = shortDate(field('[name="data"]').value);
        this.resumo.valor = valor && valor.value ? `R$ ${valor.value}` : "";
        this.resumo.horario = "";
        if (hora && duracao) {
          const [hours, mins] = hora.split(":").map(Number);
          const end = hours * 60 + mins + Number(duracao.value);
          const pad = (value) => String(value).padStart(2, "0");
          this.resumo.horario = `${hora}–${pad(Math.floor(end / 60) % 24)}:${pad(end % 60)}`;
        }
      },
    }));

    Alpine.data("bloqueioForm", (data) => ({
      diaTodo: data.diaTodo,
      allSelected: false,
      resumo: { horario: "", dia: "", espacos: "" },
      init() {
        this.form = this.$el;
        this.refresh();
      },
      boxes() {
        return Array.from(this.form.querySelectorAll('[name="espacos"]'));
      },
      toggleAll() {
        const value = !this.allSelected;
        this.boxes().forEach((box) => {
          box.checked = value;
        });
        this.refresh();
      },
      refresh() {
        const value = (name) => this.form.querySelector(`[name="${name}"]`).value;
        const checked = this.boxes().filter((box) => box.checked);
        this.allSelected = checked.length === this.boxes().length;
        this.resumo.dia = shortDate(value("data"));
        this.resumo.espacos = checked.length
          ? checked.map((box) => box.closest("label").innerText.trim()).join(", ")
          : "Escolha os espaços";
        const inicio = value("hora_inicio");
        const fim = value("hora_fim");
        this.resumo.horario = this.diaTodo ? "Dia todo" : inicio && fim ? `${inicio}–${fim}` : "Escolha o horário";
      },
    }));

    const parseMoney = (raw) => {
      // "1.234,50" e "50,00" são o padrão daqui, mas alguns teclados só têm ponto: "50.00" vale 50.
      let text = String(raw).trim();
      if (text.includes(",")) text = text.replace(/\./g, "").replace(",", ".");
      else if (/^\d{1,3}(\.\d{3})+$/.test(text)) text = text.replace(/\./g, "");
      const value = Number(text);
      return Number.isFinite(value) && value > 0 ? Math.round(value * 100) : 0;
    };
    const formatMoney = (cents) =>
      (cents / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

    Alpine.data("pdv", () => ({
      products: [],
      allowNegative: false,
      reservas: [],
      cart: {},
      query: "",
      categoria: "",
      step: "cart",
      cartOpen: false,
      forma: "",
      reservaId: "",
      recebido: "",
      init() {
        const data = JSON.parse(document.getElementById("pdv-data").textContent);
        this.products = data.produtos.map((produto) => ({
          ...produto,
          cents: Math.round(Number(produto.preco) * 100),
          search: this.plain(`${produto.nome} ${produto.codigo}`),
        }));
        this.allowNegative = data.permiteNegativo;
        this.reservas = data.reservas;
        this.restore();
        if (data.reservaSelecionada) {
          this.reservaId = data.reservaSelecionada;
          this.step = this.lines.length ? "pay" : "cart";
        }
        this.$watch("cart", () => sessionStorage.setItem(CART_KEY, JSON.stringify(this.cart)));
      },
      plain(text) {
        return text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
      },
      /* O carrinho sobrevive à troca de tela, mas respeita o catálogo e o estoque atuais. */
      restore() {
        let saved = {};
        try {
          saved = JSON.parse(sessionStorage.getItem(CART_KEY)) || {};
        } catch (error) {
          saved = {};
        }
        const cart = {};
        Object.entries(saved).forEach(([id, qty]) => {
          const produto = this.product(Number(id));
          if (!produto) return;
          const limit = produto.controla && !this.allowNegative ? Math.max(produto.estoque, 0) : qty;
          if (Math.min(qty, limit) > 0) cart[id] = Math.min(qty, limit);
        });
        this.cart = cart;
      },
      product(id) {
        return this.products.find((produto) => produto.id === id);
      },
      qty(id) {
        return this.cart[id] || 0;
      },
      matches(produto) {
        if (this.categoria && produto.categoria !== this.categoria) return false;
        return !this.query.trim() || produto.search.includes(this.plain(this.query.trim()));
      },
      isVisible(id) {
        const produto = this.product(id);
        return Boolean(produto) && this.matches(produto);
      },
      get hasVisible() {
        return this.products.some((produto) => this.matches(produto));
      },
      remaining(id) {
        const produto = this.product(id);
        return produto ? produto.estoque - this.qty(id) : 0;
      },
      canAdd(id) {
        const produto = this.product(id);
        if (!produto) return false;
        return !produto.controla || this.allowNegative || this.remaining(id) > 0;
      },
      stockLabel(id) {
        const remaining = this.remaining(id);
        return remaining > 0 ? `${remaining} un.` : "Esgotado";
      },
      stockClass(id) {
        const produto = this.product(id);
        if (!produto || this.remaining(id) <= 0) return "text-danger";
        return produto.baixo ? "text-warning" : "text-muted";
      },
      add(id) {
        if (this.canAdd(id)) this.cart = { ...this.cart, [id]: this.qty(id) + 1 };
      },
      decrease(id) {
        const cart = { ...this.cart };
        if (cart[id] > 1) cart[id] -= 1;
        else delete cart[id];
        this.cart = cart;
        if (!this.lines.length) this.step = "cart";
      },
      clear() {
        this.cart = {};
        this.step = "cart";
        this.forma = "";
        this.reservaId = "";
        this.recebido = "";
        sessionStorage.removeItem(CART_KEY);
      },
      /* Enter na busca: um leitor de código de barras digita o código e aperta Enter sozinho. */
      addFromSearch() {
        const query = this.query.trim();
        if (!query) return;
        const visible = this.products.filter((produto) => this.matches(produto));
        const match = this.products.find((produto) => produto.codigo === query) || (visible.length === 1 && visible[0]);
        if (match) {
          this.add(match.id);
          this.query = "";
        }
      },
      get lines() {
        return Object.keys(this.cart).map((key) => {
          const id = Number(key);
          const produto = this.product(id);
          return { id, nome: produto.nome, qty: this.cart[key], subtotal: produto.cents * this.cart[key] };
        });
      },
      get count() {
        return Object.values(this.cart).reduce((sum, qty) => sum + qty, 0);
      },
      get totalCents() {
        return this.lines.reduce((sum, line) => sum + line.subtotal, 0);
      },
      get totalValue() {
        return (this.totalCents / 100).toFixed(2);
      },
      get recebidoCents() {
        return this.forma === "DINHEIRO" ? parseMoney(this.recebido) : 0;
      },
      get recebidoValue() {
        return this.recebidoCents ? (this.recebidoCents / 100).toFixed(2) : "";
      },
      get recebidoShort() {
        return this.recebidoCents > 0 && this.recebidoCents < this.totalCents;
      },
      get change() {
        return this.recebidoCents > this.totalCents ? this.recebidoCents - this.totalCents : 0;
      },
      /* Sugestões de nota: as que cobrem o total. */
      get notes() {
        return [10, 20, 50, 100, 200].filter((note) => note * 100 >= this.totalCents).slice(0, 4);
      },
      get canConfirm() {
        return this.lines.length > 0 && (this.reservaId || (this.forma && !this.recebidoShort));
      },
      chooseForma(forma) {
        this.forma = forma;
        this.reservaId = "";
      },
      chooseReserva(id) {
        this.reservaId = id;
        this.forma = "";
      },
      money: formatMoney,
      /* Só a resposta da própria venda esvazia o carrinho: um aviso de outro painel não mexe nele. */
      onToast(detail) {
        if (detail.elt === this.$refs.form && detail.level !== "error") this.clear();
      },
    }));

    Alpine.data("tabPayment", (data) => ({
      forma: "",
      recebido: "",
      totalCents: Math.round(Number(data.total) * 100),
      get recebidoCents() {
        return this.forma === "DINHEIRO" ? parseMoney(this.recebido) : 0;
      },
      get recebidoValue() {
        return this.recebidoCents ? (this.recebidoCents / 100).toFixed(2) : "";
      },
      get recebidoShort() {
        return this.recebidoCents > 0 && this.recebidoCents < this.totalCents;
      },
      get change() {
        return this.recebidoCents > this.totalCents ? this.recebidoCents - this.totalCents : 0;
      },
      money: formatMoney,
    }));

    Alpine.data("productForm", (data) => ({
      controla: data.controla !== "false",
      margin: null,
      init() {
        this.form = this.$el;
        this.refresh();
      },
      refresh() {
        const value = (name) => parseMoney(this.form.querySelector(`[name="${name}"]`).value);
        this.controla = this.form.querySelector('[name="controla_estoque"]').checked;
        const preco = value("preco_venda");
        const custo = value("custo");
        this.margin = preco && custo && preco > custo ? Math.round(((preco - custo) * 100) / preco) : null;
      },
    }));

    Alpine.data("stockMove", (data) => ({
      atual: Number(data.atual),
      tipo: "ENTRADA",
      novo: 0,
      init() {
        this.form = this.$el;
        this.refresh();
      },
      input() {
        return this.form.querySelector('[name="quantidade"]');
      },
      step(delta) {
        const input = this.input();
        input.value = Math.max(0, Number(input.value || 0) + delta);
        this.refresh();
      },
      refresh() {
        const checked = this.form.querySelector('[name="tipo"]:checked');
        this.tipo = checked ? checked.value : "ENTRADA";
        const quantidade = Number(this.input().value || 0);
        if (this.tipo === "ENTRADA") this.novo = this.atual + quantidade;
        else if (this.tipo === "PERDA") this.novo = this.atual - quantidade;
        else this.novo = quantidade;
      },
    }));

    /* Painel de recebimento: soma o que está sendo cobrado e calcula o troco. */
    Alpine.data("receiveForm", (data) => ({
      forma: "",
      valor: "",
      recebido: "",
      comandaCents: Math.round(Number(data.comanda || 0) * 100),
      incluirComanda: Boolean(data.comanda),
      init() {
        this.form = this.$el;
        this.refresh();
      },
      refresh() {
        const value = (selector) => this.form.querySelector(selector);
        const forma = value('[name="forma"]:checked');
        this.forma = forma ? forma.value : "";
        this.valor = value('[name="valor"]').value;
        this.recebido = value('[name="recebido"]').value;
        const comanda = value('[name="incluir_comanda"]');
        this.incluirComanda = Boolean(comanda && comanda.checked);
      },
      get totalCents() {
        return parseMoney(this.valor) + (this.incluirComanda ? this.comandaCents : 0);
      },
      get recebidoCents() {
        return this.forma === "DINHEIRO" ? parseMoney(this.recebido) : 0;
      },
      get recebidoShort() {
        return this.recebidoCents > 0 && this.recebidoCents < this.totalCents;
      },
      get change() {
        return this.recebidoCents > this.totalCents ? this.recebidoCents - this.totalCents : 0;
      },
      money: formatMoney,
    }));

    /* Fechamento: dono e gerente veem a diferença enquanto digitam. */
    Alpine.data("closeRegister", (data) => ({
      esperado: data.esperado ? parseMoney(data.esperado) : 0,
      contado: "",
      refresh() {
        this.contado = this.$root.querySelector('[name="saldo_conferido"]').value;
      },
      get diferenca() {
        return parseMoney(this.contado) - this.esperado;
      },
      money: formatMoney,
    }));

    Alpine.data("dayPresets", () => ({
      apply(values) {
        this.$root.querySelectorAll('[name="dias"]').forEach((box) => {
          box.checked = values.includes(Number(box.value));
        });
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
