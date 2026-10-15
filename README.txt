REPLACE server.py AT APP ROOT (overwrite completely).

Crash cause: @app.route("/expenses") was stacked onto clear_sample_expenses.
This file has:
  GET  /expenses              -> expense_list
  POST /expenses/clear-sample -> clear_sample_expenses (at end of file)
  /admin/currency             -> admin_currency

After deploy, logs must NOT say Worker failed to boot.
