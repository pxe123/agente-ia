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
};
