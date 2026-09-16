#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Webbgränssnitt för Blöjkalkylatorn (Flask).

Kör:  python3 web.py
Öppna sedan http://127.0.0.1:5000 i webbläsaren.
"""

import os
from flask import Flask, request, render_template_string

import blojkalkylatorn as bk

app = Flask(__name__)

STORES = ["willys", "hemkop", "apotea", "coop", "apoteket", "mathem", "citygross", "ica"]

TEMPLATE = """
<!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Blöjkalkylatorn 🍼</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif; margin: 0; padding: 20px;
         background: #f5f5f7; color: #1d1d1f; }
  .wrap { max-width: 1050px; margin: 0 auto; }
  h1 { font-size: 1.6em; margin-bottom: 4px; }
  .sub { color: #888; margin-top: 0; }
  form, .section { background: #fff; padding: 18px 20px; border-radius: 12px;
                   box-shadow: 0 1px 3px rgba(0,0,0,.1); }
  form { margin-bottom: 20px; }
  .section { margin-top: 15px; }
  h2 { margin-top: 0; font-size: 1.15em; }
  label { display: block; margin: 10px 0 4px; font-weight: 600; font-size: .95em; }
  input[type=text], select { width: 100%; padding: 8px; border: 1px solid #ccc;
                             border-radius: 6px; font-size: 1em; box-sizing: border-box; }
  .stores { display: flex; flex-wrap: wrap; gap: 12px; margin: 6px 0; }
  .stores label { font-weight: normal; display: inline-flex; align-items: center; gap: 5px; margin: 0; }
  .checks { margin: 10px 0; }
  .checks label { font-weight: normal; display: inline-flex; align-items: center; gap: 6px; margin: 0 16px 0 0; }
  button { background: #0071e3; color: #fff; border: none; padding: 11px 22px;
           border-radius: 8px; font-size: 1em; cursor: pointer; margin-top: 12px; }
  button:hover { background: #0077ed; }
  table { width: 100%; border-collapse: collapse; }
  th, td { padding: 8px 10px; text-align: left; border-bottom: 1px solid #eee; font-size: .95em; }
  th { background: #fafafa; }
  td.num { text-align: right; white-space: nowrap; }
  .cheap { font-weight: 700; color: #1a7f37; }
  .star { color: #e68a00; }
  .muted { color: #888; }
  .warn { background: #fff3cd; padding: 8px 12px; border-radius: 6px; margin: 4px 0; font-size: .9em; }
  .coupon { background: #eef4ff; padding: 8px 12px; border-radius: 6px; margin: 6px 0; font-size: .9em; }
  .cond { color: #555; font-size: .85em; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Blöjkalkylatorn 🍼</h1>
  <p class="sub">Jämför riktiga blöjpriser (kr/blöja) över svenska butiker.</p>

  <form method="post">
    <label for="sok">Sökord</label>
    <input type="text" name="sok" id="sok" value="{{ form.sok }}">

    <label for="marke">Märke</label>
    <select name="marke" id="marke">
      <option value="">Alla</option>
      <option value="Libero" {% if form.marke == 'Libero' %}selected{% endif %}>Libero</option>
      <option value="Pampers" {% if form.marke == 'Pampers' %}selected{% endif %}>Pampers</option>
    </select>

    <label>Butiker</label>
    <div class="stores">
      {% for s in stores %}
      <label><input type="checkbox" name="butik_{{ s }}" value="1" {% if form.checked[s] %}checked{% endif %}> {{ s }}</label>
      {% endfor %}
    </div>
    <p class="muted" style="margin:2px 0">ICA är långsam (webbläsare för bot-skydd).</p>

    <div class="checks">
      <label><input type="checkbox" name="med_kampanj" value="1" {% if form.med_kampanj %}checked{% endif %}> Räkna in kampanjpris</label>
      <label><input type="checkbox" name="kuponger" value="1" {% if form.kuponger %}checked{% endif %}> Använd kuponger (kuponger.json)</label>
      <label><input type="checkbox" name="jmf_pris" value="1" {% if form.jmf_pris %}checked{% endif %}> Jämförpris från Apotea (långsamt)</label>
    </div>

    <label for="ica_butik">ICA-butik (valfritt, t.ex. "maxi stockholm")</label>
    <input type="text" name="ica_butik" id="ica_butik" value="{{ form.ica_butik }}">

    <button type="submit">Jämför priser</button>
  </form>

  {% if result %}
    <div class="section">
      <h2>Resultat — sorterat på billigast kr/blöja</h2>
      {% if result.ica_store_name %}<p class="muted">ICA-butik: {{ result.ica_store_name }}</p>{% endif %}
      <table>
        <tr><th>#</th><th>Butik</th><th class="num">Pris/fp</th><th class="num">Antal</th>
            <th class="num">kr/blöja</th><th>Märke</th><th>Produkt</th></tr>
        {% for p in result.produkter %}
        <tr>
          <td>{{ loop.index }}</td>
          <td>{{ p.store }}</td>
          <td class="num">{{ fmt(p.price) }}</td>
          <td class="num">{{ p.count ~ ' st' if p.count else '-' }}</td>
          <td class="num {% if loop.index == 1 and p.price_per %}cheap{% endif %}">{{ fmt(p.price_per) }}</td>
          <td>{{ p.brand }}</td>
          <td>{{ p.name }}{% if p.kampanj %} <span class="star" title="{{ p.kampanj }}">★</span>{% endif %}</td>
        </tr>
        {% endfor %}
      </table>
      {% if result.utan_pris %}
        <p class="muted">ℹ️ {{ result.utan_pris|length }} produkt(er) saknar antal/jämförpris.</p>
      {% endif %}
    </div>

    {% if result.kuponger %}
    <div class="section">
      <h2>Kuponger (med villkor att verifiera)</h2>
      {% for c in result.kuponger %}
      <div class="coupon">
        <strong>{{ c.beskrivning or c.typ }}</strong>
        <div class="cond">{{ villkor(c) }}</div>
      </div>
      {% endfor %}
    </div>
    {% endif %}

    {% if result.kampanjer %}
    <div class="section">
      <h2>★ Kampanjer / erbjudanden hos butikerna</h2>
      {% for p in result.kampanjer %}
      <p>★ <strong>{{ p.store }}</strong>: {{ p.name }} → {{ p.kampanj }}{% if p.kampanj_per %} → <strong>{{ fmt(p.kampanj_per) }}/blöja</strong>{% endif %}</p>
      {% endfor %}
    </div>
    {% endif %}

    {% if result.varningar %}
    <div class="section">
      <h2>Varningar</h2>
      {% for w in result.varningar %}<div class="warn">{{ w }}</div>{% endfor %}
    </div>
    {% endif %}
  {% endif %}
</div>
</body>
</html>
"""


@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    form = {
        "sok": "blöjor",
        "marke": "",
        "checked": {s: (s != "ica") for s in STORES},
        "med_kampanj": False,
        "kuponger": False,
        "jmf_pris": False,
        "ica_butik": "",
    }

    if request.method == "POST":
        form["sok"] = request.form.get("sok", "blöjor").strip() or "blöjor"
        form["marke"] = request.form.get("marke", "").strip()
        form["med_kampanj"] = bool(request.form.get("med_kampanj"))
        form["kuponger"] = bool(request.form.get("kuponger"))
        form["jmf_pris"] = bool(request.form.get("jmf_pris"))
        form["ica_butik"] = request.form.get("ica_butik", "").strip()
        form["checked"] = {s: bool(request.form.get("butik_" + s)) for s in STORES}

        butiker_list = [s for s in STORES if form["checked"][s]]
        butiker = ",".join(butiker_list) if butiker_list else "willys,apotea"

        kuponger_path = None
        if form["kuponger"]:
            p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kuponger.json")
            if os.path.exists(p):
                kuponger_path = p

        result = bk.jamfor(
            sok=form["sok"],
            butiker=butiker,
            marke=form["marke"] or None,
            med_kampanj=form["med_kampanj"],
            kuponger_path=kuponger_path,
            jmf_pris=form["jmf_pris"],
            ica_butik=form["ica_butik"] or None,
        )

    return render_template_string(
        TEMPLATE,
        result=result,
        form=form,
        stores=STORES,
        fmt=bk.format_kr,
        villkor=bk.coupon_villkor,
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)