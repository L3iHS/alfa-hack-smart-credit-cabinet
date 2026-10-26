import { useEffect, useId, useRef, useState } from "react";
import { api, errorMessage } from "../api/client";
import type { Application } from "../api/types";
import DealStatus, { completionLabels } from "./DealStatus";
import PaymentTermsView, { amountLabel } from "./PaymentTermsView";
import ReviewCommandFeedback from "./ReviewCommandFeedback";
import type { ReviewCommand } from "./useReviewCommand";
import { dateTime, money } from "./shared";

const fieldLabels = { expected_version: "Версия заявки", terms_confirmed: "Подтверждение условий", reason: "Причина отмены" };

export default function DealPanel({ application, staff, command, locked }: {
  application: Application; staff: boolean; command: ReviewCommand; locked: boolean;
}) {
  const deal = application.deal;
  const id = useId();
  const [confirmed, setConfirmed] = useState(false);
  const [modal, setModal] = useState<"cancel" | "complete" | null>(null);
  const [reason, setReason] = useState("");
  const [validation, setValidation] = useState("");
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const cancelTrigger = useRef<HTMLButtonElement>(null);
  const completeTrigger = useRef<HTMLButtonElement>(null);
  const previousModal = useRef<typeof modal>(null);
  const downloadActive = useRef(false);
  const disabled = locked || command.busy || !!command.pending || command.conflict || command.needsRefresh;
  const can = (action: "confirm_deal" | "complete_deal" | "cancel_deal") => deal?.available_actions.includes(action);
  useEffect(() => { setConfirmed(false); }, [deal?.id, application.version]);
  useEffect(() => {
    if (deal?.status === "completed" || deal?.status === "cancelled") setModal(null);
  }, [deal?.status]);
  useEffect(() => {
    if (modal) {
      dialog.current?.showModal();
      dialog.current?.querySelector<HTMLElement>(modal === "cancel" ? "textarea" : "button")?.focus();
    } else if (previousModal.current) {
      dialog.current?.close();
      const trigger = previousModal.current === "cancel" ? cancelTrigger.current : completeTrigger.current;
      trigger?.focus({ preventScroll: true });
    }
    previousModal.current = modal;
  }, [modal]);
  function close() { if (!command.busy) { setModal(null); setValidation(""); } }
  function send(action: "prepare" | "confirm" | "complete" | "cancel") {
    if (disabled) return;
    const body: Record<string, unknown> = { expected_version: application.version };
    if (action === "confirm") { if (!confirmed) return; body.terms_confirmed = true; }
    if (action === "cancel") {
      const value = reason.trim();
      if (!value || Array.from(value).length > 1000) { setValidation("Укажите причину отмены: от 1 до 1000 символов"); return; }
      body.reason = value;
    }
    setValidation("");
    void command.send(`/applications/${application.id}/deal/${action}`, body);
  }
  async function download() {
    if (downloadActive.current) return;
    downloadActive.current = true; setDownloading(true); setDownloadError("");
    try {
      const file = await api<Blob>(`/applications/${application.id}/deal/document`, { responseType: "blob" });
      const url = URL.createObjectURL(file);
      const link = document.createElement("a");
      link.href = url;
      link.download = `Условия-${(deal?.reference || application.display_number).replace(/[^\p{L}\p{N}_-]/gu, "-")}.md`;
      document.body.appendChild(link);
      try { link.click(); } finally { link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
    } catch (value) { setDownloadError(errorMessage(value)); }
    finally { downloadActive.current = false; setDownloading(false); }
  }
  const terminal = deal?.status === "completed" || deal?.status === "cancelled";
  const next = !deal
    ? staff ? "Подготовьте окончательные условия для клиента" : "Сотрудник подготовит окончательные условия"
    : deal.status === "prepared"
      ? staff ? "Клиент должен подтвердить условия" : "Ознакомьтесь с условиями и подтвердите их"
      : deal.status === "confirmed"
        ? staff ? "Клиент подтвердил условия. Завершите оформление" : "Сотрудник завершит оформление"
        : null;
  return <section className="panel deal-panel" aria-labelledby={`${id}-title`}>
    <div className="deal-heading">
      <h2 id={`${id}-title`}>Оформление сделки</h2>
      <DealStatus deal={deal} />
    </div>
    {deal && <>
      <div className="deal-document-line">
        <span className="muted">{deal.reference}</span>
        <button type="button" className="button secondary" disabled={downloading} onClick={() => void download()} aria-label="Скачать условия в Markdown">{downloading ? "Скачиваем…" : "Скачать условия"}</button>
      </div>
      {downloadError && <p className="notice error" role="alert">{downloadError}</p>}
      <dl className="deal-key-terms">
        <div><dt>{amountLabel(deal.payment_terms.payment_kind)}</dt><dd>{money(deal.amount_kopecks)}</dd></div>
        <div><dt>Срок</dt><dd>{deal.term_months} мес.</dd></div>
      </dl>
    </>}
    {next && <p className="deal-next-step">{next}</p>}
    {deal?.status === "completed" && deal.completed_at && <p className="deal-terminal-date">Оформлено {dateTime(deal.completed_at)}</p>}
    {deal?.status === "cancelled" && <div className="deal-cancellation">
      {deal.cancelled_at && <p>Отменено {dateTime(deal.cancelled_at)}</p>}
      <p className="multiline"><strong>Причина: </strong>{deal.cancel_reason}</p>
    </div>}
    {!staff && can("confirm_deal") && <label className="deal-confirmation">
      <input type="checkbox" checked={confirmed} disabled={disabled} onChange={event => setConfirmed(event.target.checked)} />
      <span>Я ознакомился с окончательными условиями и подтверждаю их</span>
    </label>}
    {!terminal && <div className="review-buttons deal-actions">
      {can("cancel_deal") && <button ref={cancelTrigger} type="button" className="button secondary" disabled={disabled} onClick={() => { setValidation(""); setModal("cancel"); }}>Отменить оформление</button>}
      {staff && application.available_actions.includes("prepare_deal") && !deal && <button type="button" className="button primary" disabled={disabled} onClick={() => send("prepare")}>Подготовить оформление</button>}
      {!staff && can("confirm_deal") && <button type="button" className="button primary" disabled={disabled || !confirmed} onClick={() => send("confirm")}>Подтвердить условия</button>}
      {staff && can("complete_deal") && <button ref={completeTrigger} type="button" className="button primary" disabled={disabled} onClick={() => { setValidation(""); setModal("complete"); }}>Завершить оформление</button>}
    </div>}
    {!modal && <ReviewCommandFeedback command={command} labels={fieldLabels} />}
    {deal && <details className="deal-payment-details"><summary>Подробные условия и платежи</summary><PaymentTermsView terms={deal.payment_terms} collapseAssumptions /></details>}
    <p className="deal-demo-note">Демонстрационное оформление: юридическое подписание и банковский перевод не выполняются.</p>
    <dialog ref={dialog} className="deal-dialog" aria-labelledby={`${id}-dialog-title`} aria-describedby={`${id}-dialog-description`} onCancel={event => { event.preventDefault(); close(); }}>
      <h2 id={`${id}-dialog-title`}>{modal === "cancel" ? "Отменить оформление?" : "Завершить оформление?"}</h2>
      <p id={`${id}-dialog-description`}>{modal === "cancel" ? "Отмена окончательная. Кредитное решение и история заявки сохранятся." : `Будет зафиксирован результат «${deal ? completionLabels[deal.completion_kind] : "Оформление завершено"}». Изменить его после завершения нельзя.`}</p>
      {modal === "cancel" && <label className="field"><span>Причина отмены</span><textarea value={reason} rows={3} maxLength={1000} disabled={command.busy || !!command.pending} aria-invalid={!!validation} aria-describedby={validation ? `${id}-validation` : undefined} onChange={event => { setReason(event.target.value); setValidation(""); }} /></label>}
      {validation && <p className="notice error" role="alert" id={`${id}-validation`}>{validation}</p>}
      {modal && <ReviewCommandFeedback command={command} labels={fieldLabels} />}
      <div className="review-buttons">
        <button type="button" className="button secondary" disabled={command.busy} onClick={close}>Вернуться</button>
        <button type="button" className="button primary" disabled={disabled} onClick={() => send(modal === "cancel" ? "cancel" : "complete")}>{modal === "cancel" ? "Отменить оформление" : "Завершить оформление"}</button>
      </div>
    </dialog>
  </section>;
}
