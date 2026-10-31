/** Tokens do QuadraNaMão!: as cores vêm de CSS variables (ver assets/css/app.css). */
const token = (name) => `rgb(var(--color-${name}) / <alpha-value>)`;

module.exports = {
  content: ["./templates/**/*.html", "./apps/**/templates/**/*.html", "./apps/**/*.py", "./static/js/*.js"],
  theme: {
    extend: {
      colors: {
        background: token("background"),
        surface: token("surface"),
        "surface-2": token("surface-2"),
        border: token("border"),
        primary: token("primary"),
        "on-primary": token("on-primary"),
        accent: token("accent"),
        text: token("text"),
        muted: token("muted"),
        success: token("success"),
        warning: token("warning"),
        danger: token("danger"),
      },
      fontFamily: {
        sans: ["Inter Variable", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
      },
      borderRadius: {
        xl: "0.875rem",
        "2xl": "1.125rem",
      },
      boxShadow: {
        sheet: "0 -8px 40px rgb(0 0 0 / 0.35)",
        card: "0 1px 2px rgb(0 0 0 / 0.12)",
      },
    },
  },
  plugins: [],
};
