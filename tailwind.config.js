/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "panel/templates/**/*.html",
    "panel/static/js/**/*.js"
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
  safelist: [
    { pattern: /^(bg|text|border|hover:bg|hover:text)-(teal|emerald)-(50|100|200|600|700|800|900)$/ },
    "text-white",
    "shadow-sm",
  ],
};
