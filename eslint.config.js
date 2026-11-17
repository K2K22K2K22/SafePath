const js = require("@eslint/js");
const globals = require("globals");

module.exports = [
  {
    ignores: ["node_modules/**", "web/static/web/css/app.css"],
  },
  {
    files: ["web/static/web/js/**/*.js"],
    languageOptions: {
      ecmaVersion: "latest",
      globals: {
        ...globals.browser,
        L: "readonly",
      },
      sourceType: "script",
    },
    rules: js.configs.recommended.rules,
  },
];
