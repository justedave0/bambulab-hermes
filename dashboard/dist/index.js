/**
 * Bambu Lab dashboard tab.
 *
 * Plain IIFE — no build step. Uses window.__HERMES_PLUGIN_SDK__ globals
 * (React, components, hooks, fetchJSON) + window.__HERMES_PLUGINS__.register.
 *
 * Dynamic, unlimited "add printer" form. Each printer row: name / ip / serial
 * plus a MASKED access-code field (type="password"). The printer's name is
 * its id (auto-derived, e.g. "H2S" -> h2s); no id field is shown to the user.
 * Codes are never shown back from the backend (only a has_code flag);
 * a blank code on save keeps the existing one.
 *
 * Per-printer "Test" button: connects over MQTT with the stored code and
 * reports a live snapshot on success, or the exact error on failure.
 *
 * NOTE on button styling: the SDK Button default text color is near-black
 * (text-primary-foreground) — on dark fills it is INVISIBLE (verified against
 * the live dashboard's computed styles). Every non-primary button here sets an
 * explicit light text color (text-foreground / text-destructive).
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

  var BTN_BASE = "inline-flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors cursor-pointer";
  var BTN_OUTLINE = BTN_BASE + " border border-border bg-background/40 text-foreground hover:bg-foreground/10";
  var BTN_PRIMARY = BTN_BASE + " bg-primary text-primary-foreground hover:opacity-90";
  var BTN_DANGER = BTN_BASE + " border border-destructive/40 bg-transparent text-destructive hover:bg-destructive/10";

  function slugify(v) {
    return String(v || "").toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/^-+|-+$/g, "");
  }

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
          h(CardTitle, { className: "text-base" }, p.name || "New printer"),
          h(Badge, { variant: p.has_code ? "default" : "outline" }, p.has_code ? "code set" : "no code")
        )
      ),
      h(CardContent, { className: "flex flex-col gap-4" },
        h("div", { className: "grid grid-cols-1 md:grid-cols-3 gap-3" },
          Field({ label: "Name", value: p.name, placeholder: "e.g. H2S", onChange: function (v) { props.onChange(p.rowId, "name", v); } }),
          Field({ label: "IP address", value: p.ip, placeholder: "e.g. 192.168.0.50", onChange: function (v) { props.onChange(p.rowId, "ip", v); } }),
          Field({ label: "Serial number", value: p.serial, placeholder: "on the printer label or in its settings", onChange: function (v) { props.onChange(p.rowId, "serial", v); } })
        ),
        h("div", { className: "flex items-end gap-3" },
          h("div", { className: "flex-1" },
            Field({
              label: "Access code (LAN mode, shown on the printer) \u2014 leave blank to keep",
              value: "",
              type: "password",
              placeholder: p.has_code ? "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" : "enter access code",
              onChange: function (v) { props.onChange(p.rowId, "code", v); }
            })
          ),
          h(Button, {
            onClick: function () { props.onTest(p); },
            disabled: p.testing,
            className: BTN_OUTLINE
          }, p.testing ? "Testing\u2026" : "Test")
        ),
        p.test_result ? h("p", { className: "text-xs " + (p.test_ok ? "text-emerald-400" : "text-red-400") }, p.test_result) : null,
        h(Button, {
          onClick: function () { props.onRemove(p.rowId); },
          className: BTN_DANGER + " self-end"
        }, "Remove")
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

    function rowKey(p) { return p.rowId; }

    function load() {
      setLoading(true);
      SDK.fetchJSON("/api/plugins/bambulab/printers")
        .then(function (d) {
          var rows = ((d && d.printers) || []).map(function (p, i) {
            var np = {};
            for (var k in p) { np[k] = p[k]; }
            np.rowId = p.slug || ("loaded-" + i);
            np.slug = slugify(p.name) || p.slug;
            return np;
          });
          setPrinters(rows);
        })
        .catch(function (e) { setMsg("Load error: " + e); })
        .finally(function () { setLoading(false); });
    }

    useEffect(function () { load(); }, []);

    function addPrinter() {
      var row = {
        rowId: "r" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
        slug: "", name: "", ip: "", serial: "",
        enabled: true, has_code: false, code: ""
      };
      setPrinters(printers.concat([row]));
    }

    function patchRow(rowId, patch) {
      setPrinters(printers.map(function (p) {
        if (rowKey(p) !== rowId) return p;
        var np = {};
        for (var k in p) { np[k] = p[k]; }
        for (var k2 in patch) { np[k2] = patch[k2]; }
        return np;
      }));
    }

    function change(rowId, key, value) {
      if (key === "name") {
        patchRow(rowId, { name: value, slug: slugify(value) });
        return;
      }
      patchRow(rowId, { [key]: value });
    }

    function remove(rowId) {
      setPrinters(printers.filter(function (p) { return rowKey(p) !== rowId; }));
    }

    function save() {
      setSaving(true);
      setMsg("");
      var payload = printers.map(function (p) {
        var np = {};
        for (var k in p) { if (k !== "rowId") { np[k] = p[k]; } }
        np.slug = slugify(p.name) || p.slug;
        return np;
      });
      SDK.fetchJSON("/api/plugins/bambulab/printers", {
        method: "POST",
        body: JSON.stringify({ printers: payload })
      })
        .then(function (d) { setMsg(d && d.ok ? "Saved \u2014 " + d.count + " printer(s)." : "Saved (details in server log)."); load(); })
        .catch(function (e) { setMsg("Save error: " + e); })
        .finally(function () { setSaving(false); });
    }

    function testRow(p) {
      var slug = slugify(p.name) || p.slug;
      if (!slug) {
        patchRow(p.rowId, { test_ok: false, test_result: "\u2717 give the printer a name first" });
        return;
      }
      patchRow(p.rowId, { testing: true, test_result: null, test_ok: null });
      SDK.fetchJSON("/api/plugins/bambulab/test/" + encodeURIComponent(slug), { method: "POST" })
        .then(function (d) {
          if (d && d.ok) {
            var bits = [];
            if (d.state !== undefined && d.state !== null) bits.push("state " + d.state);
            if (d.progress !== undefined && d.progress !== null) bits.push("progress " + d.progress + "%");
            if (d.nozzle && d.nozzle[0] !== undefined) bits.push("nozzle " + d.nozzle[0] + "\u00b0C");
            if (d.file) bits.push("file " + d.file);
            patchRow(p.rowId, { test_ok: true, test_result: "\u2713 connected \u2014 configuration works" + (bits.length ? " (" + bits.join(", ") + ")" : "") });
          } else {
            patchRow(p.rowId, { test_ok: false, test_result: "\u2717 " + ((d && d.error) || (d && d.detail) || "unknown error") + " \u2014 press Save first if this printer is new" });
          }
        })
        .catch(function (e) { patchRow(p.rowId, { test_ok: false, test_result: "\u2717 " + e + " \u2014 press Save first if this printer is new" }); })
        .finally(function () { patchRow(p.rowId, { testing: false }); });
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
            "Add as many printers as you like. The access code is the one shown on the printer when LAN mode is enabled; it is masked here and stored securely on this machine \u2014 never shared. Use Test to check that a printer is reachable."),
          h("div", { className: "flex flex-col gap-4" },
            loading[0]
              ? h("p", { className: "text-sm text-muted-foreground" }, "Loading\u2026")
              : (printers.length === 0
                  ? h("p", { className: "text-sm text-muted-foreground" }, "No printers yet \u2014 add one below.")
                  : printers.map(function (p) {
                      return h(PrinterRow, { key: rowKey(p), p: p, onChange: change, onRemove: remove, onTest: testRow });
                    }))
          ),
          h("div", { className: "flex items-center gap-3" },
            h(Button, { onClick: addPrinter, className: BTN_OUTLINE }, "Add printer"),
            h(Button, { onClick: save, disabled: saving[0], className: BTN_PRIMARY }, saving[0] ? "Saving\u2026" : "Save"),
            h(Button, { onClick: refreshStatus, className: BTN_OUTLINE }, "Refresh status")
          ),
          msg[0] ? h("p", { className: "text-xs text-muted-foreground" }, msg[0]) : null,
          status[0] ? h("pre", { className: "text-xs overflow-auto max-h-72 border border-border p-3" }, JSON.stringify(status[0], null, 2)) : null
        )
      )
    );
  }

  window.__HERMES_PLUGINS__.register("bambulab", BambuLabPage);
})();
