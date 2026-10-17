/**
 * Bambu Lab dashboard tab.
 *
 * Plain IIFE — no build step. Uses window.__HERMES_PLUGIN_SDK__ globals
 * (React, components, hooks, fetchJSON) + window.__HERMES_PLUGINS__.register.
 *
 * Dynamic, unlimited "add printer" form. Each printer row: name / slug / ip /
 * serial inputs plus a MASKED access-code field (type="password").
 * Codes are never shown back from the backend (only a has_code flag);
 * a blank code on save keeps the existing one.
 */
(function () {
  "use strict";

  var SDK = window.__HERMES_PLUGIN_SDK__;
  var React = SDK.React;
  var components = SDK.components;
  var Card = components.Card, CardHeader = components.CardHeader,
      CardTitle = components.CardTitle, CardContent = components.CardContent,
      Badge = components.Badge, Button = components.Button,
      Input = components.Input, Label = components.Label;
  var useState = SDK.hooks.useState, useEffect = SDK.hooks.useEffect;
  var h = React.createElement;

  function Field(props) {
    return h("div", { className: "flex flex-col gap-1" },
      h(Label, { className: "text-xs text-muted-foreground" }, props.label),
      h(Input, {
        value: props.value || "",
        type: props.type || "text",
        placeholder: props.placeholder || "",
        onChange: function (e) { props.onChange(e.target.value); }
      })
    );
  }

  function PrinterRow(props) {
    var p = props.p;
    return h(Card, { className: "border" },
      h(CardHeader, null,
        h("div", { className: "flex items-center justify-between" },
          h(CardTitle, { className: "text-base" }, p.name || p.slug || "New printer"),
          h(Badge, { variant: p.has_code ? "default" : "outline" }, p.has_code ? "code set" : "no code")
        )
      ),
      h(CardContent, { className: "flex flex-col gap-4" },
        h("div", { className: "grid grid-cols-2 md:grid-cols-4 gap-3" },
          Field({ label: "Name", value: p.name, placeholder: "H2S", onChange: function (v) { props.onChange(p.slug, "name", v); } }),
          Field({ label: "Slug (id)", value: p.slug, placeholder: "h2s", onChange: function (v) { props.onChange(p.slug, "slug", v); } }),
          Field({ label: "IP address", value: p.ip, placeholder: "192.168.0.45", onChange: function (v) { props.onChange(p.slug, "ip", v); } }),
          Field({ label: "Serial", value: p.serial, placeholder: "0938AC612200056", onChange: function (v) { props.onChange(p.slug, "serial", v); } })
        ),
        h("div", { className: "flex items-end gap-3" },
          h("div", { className: "flex-1" },
            Field({
              label: "Access code (LAN / local mode) — leave blank to keep",
              value: "",
              type: "password",
              placeholder: p.has_code ? "••••••••" : "enter access code",
              onChange: function (v) { props.onChange(p.slug, "code", v); }
            })
          ),
          h(Button, {
            onClick: function () { props.onRemove(p.slug); },
            className: "self-end border border-destructive/40 text-destructive hover:bg-destructive/10"
          }, "Remove")
        )
      )
    );
  }

  function BambuLabPage() {
    var state = useState(null);
    var printers = state[0] === null ? [] : state[0];
    var setPrinters = state[1];

    var loading = useState(true), setLoading = loading[1];
    var saving = useState(false), setSaving = saving[1];
    var status = useState(null), setStatus = status[1];
    var msg = useState(""), setMsg = msg[1];

    function load() {
      setLoading(true);
      SDK.fetchJSON("/api/plugins/bambulab/printers")
        .then(function (d) { setPrinters((d && d.printers) || []); })
        .catch(function (e) { setMsg("Load error: " + e); })
        .finally(function () { setLoading(false); });
    }

    useEffect(function () { load(); }, []);

    function addPrinter() {
      var row = {
        slug: "p" + Date.now().toString(36),
        name: "", ip: "", serial: "",
        enabled: true, has_code: false, code: ""
      };
      setPrinters(printers.concat([row]));
    }

    function change(slug, key, value) {
      setPrinters(printers.map(function (p) {
        if (p.slug !== slug) return p;
        var np = {};
        for (var k in p) { np[k] = p[k]; }
        if (key === "slug") { np.slug = value; }
        np[key] = value;
        return np;
      }));
    }

    function remove(slug) {
      setPrinters(printers.filter(function (p) { return p.slug !== slug; }));
    }

    function save() {
      setSaving(true);
      setMsg("");
      SDK.fetchJSON("/api/plugins/bambulab/printers", {
        method: "POST",
        body: JSON.stringify({ printers: printers })
      })
        .then(function (d) { setMsg(d && d.ok ? "Saved — " + d.count + " printer(s)." : "Saved (details in server log)."); load(); })
        .catch(function (e) { setMsg("Save error: " + e); })
        .finally(function () { setSaving(false); });
    }

    function refreshStatus() {
      setStatus({ loading: true });
      SDK.fetchJSON("/api/plugins/bambulab/status")
        .then(function (d) { setStatus(d); })
        .catch(function (e) { setStatus({ error: String(e) }); });
    }

    return h("div", { className: "flex flex-col gap-6" },
      h(Card, null,
        h(CardHeader, null,
          h("div", { className: "flex items-center gap-3" },
            h(CardTitle, { className: "text-lg" }, "Bambu Lab Printers"),
            h(Badge, { variant: "outline" }, "local MQTT"),
            h(Badge, { variant: "outline" }, "unlimited")
          )
        ),
        h(CardContent, { className: "flex flex-col gap-4" },
          h("p", { className: "text-sm text-muted-foreground" },
            "Add as many printers as you like. Access codes are masked, stored securely in .env (BAMBLAB_KEY_<slug>), never in config.yaml and never in the shared repo."),
          h("div", { className: "flex flex-col gap-4" },
            loading[0]
              ? h("p", { className: "text-sm text-muted-foreground" }, "Loading…")
              : (printers.length === 0
                  ? h("p", { className: "text-sm text-muted-foreground" }, "No printers yet — add one below.")
                  : printers.map(function (p) {
                      return h(PrinterRow, { key: p.slug, p: p, onChange: change, onRemove: remove });
                    }))
          ),
          h("div", { className: "flex items-center gap-3" },
            h(Button, { onClick: addPrinter, className: "border border-border bg-background/40 hover:bg-foreground/10" }, "Add printer"),
            h(Button, { onClick: save, disabled: saving[0], className: "bg-primary text-primary-foreground hover:opacity-90" }, saving[0] ? "Saving…" : "Save"),
            h(Button, { onClick: refreshStatus, className: "border border-border bg-background/40 hover:bg-foreground/10" }, "Refresh status")
          ),
          msg[0] ? h("p", { className: "text-xs text-muted-foreground" }, msg[0]) : null,
          status[0] ? h("pre", { className: "text-xs overflow-auto max-h-72 border border-border p-3" }, JSON.stringify(status[0], null, 2)) : null
        )
      )
    );
  }

  window.__HERMES_PLUGINS__.register("bambulab", BambuLabPage);
})();
