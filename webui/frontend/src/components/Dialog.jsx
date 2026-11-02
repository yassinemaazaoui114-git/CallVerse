// A modal confirmation dialog used by the Manage screen: it names the exact record, keeps Tab / Shift+Tab
// inside (and the focus on the dialog itself while every control is disabled), closes on Escape unless a
// request is in flight, and gives the focus back to the control that opened it. The approvals screen has the
// same behaviour written inline (step 4); this is the reusable version for the newer screens.
import { useEffect, useRef } from "react";

const FOCUSABLE = "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";

export default function Dialog({ title, children, onClose, busy = false, opener = null, labelledBy }) {
  const ref = useRef(null);
  const busyRef = useRef(busy);
  busyRef.current = busy;

  useEffect(() => {
    if (ref.current) ref.current.focus();
    const back = opener;
    return () => { if (back && typeof back.focus === "function") back.focus(); };
  }, [opener]);

  useEffect(() => {
    const onKey = (e) => {
      const dialog = ref.current;
      if (!dialog) return;
      if (e.key === "Escape") {
        if (!busyRef.current) { e.preventDefault(); onClose(); }
        return;
      }
      if (e.key !== "Tab") return;
      const focusable = [...dialog.querySelectorAll(FOCUSABLE)];
      if (focusable.length === 0) { e.preventDefault(); dialog.focus(); return; }
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (!dialog.contains(document.activeElement)) { e.preventDefault(); (e.shiftKey ? last : first).focus(); return; }
      if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      else if (e.shiftKey && (document.activeElement === first || document.activeElement === dialog)) { e.preventDefault(); last.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const id = labelledBy || "dialog-title";
  return (
    <div className="confirm-backdrop" role="presentation">
      <div className="panel confirm" role="dialog" aria-modal="true" aria-labelledby={id} ref={ref} tabIndex={-1}>
        <h2 id={id}>{title}</h2>
        {children}
      </div>
    </div>
  );
}
