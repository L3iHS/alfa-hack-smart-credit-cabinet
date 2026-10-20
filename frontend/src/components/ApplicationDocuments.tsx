import { useState, type FormEvent } from "react";
import { api, ApiError, errorMessage } from "../api/client";
import type {
  Application,
  ApplicationDocument,
  DocumentType,
  SubmissionPolicy,
} from "../api/types";
import { dateTime, ErrorPanel, Loading, useResource } from "./shared";

export const documentLabels: Record<DocumentType, string> = {
  financial_statement: "Финансовая отчётность",
  equipment_invoice: "Счёт на оборудование",
};
function DocumentUpload({
  documentType,
  acceptedContentTypes,
  busy,
  disabled,
  onSubmit,
}: {
  documentType: DocumentType;
  acceptedContentTypes: string[];
  busy: boolean;
  disabled: boolean;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  // Имя сбрасывается вместе с нативным полем при обновлении списка документов.
  const [selectedName, setSelectedName] = useState("");
  const label = documentLabels[documentType];
  return (
    <form
      className="document-upload"
      onSubmit={onSubmit}
      onReset={() => setSelectedName("")}
    >
      <label
        className="document-picker"
        htmlFor={`file-${documentType}`}
        data-selected={Boolean(selectedName)}
      >
        <span className="file-picker-button" aria-hidden="true">
          Выбрать файл
        </span>
        <span className="file-picker-name" aria-hidden="true">
          {selectedName || "Файл не выбран"}
        </span>
        <input
          id={`file-${documentType}`}
          name="file"
          type="file"
          aria-label={`Файл: ${label}`}
          onChange={(event) =>
            setSelectedName(event.currentTarget.files?.[0]?.name || "")
          }
          accept={acceptedContentTypes.join(",")}
          disabled={disabled}
        />
      </label>
      <button
        className="button secondary"
        type="submit"
        aria-label={`Загрузить: ${label}`}
        disabled={disabled}
      >
        {busy ? "Сохраняем…" : "Загрузить"}
      </button>
    </form>
  );
}

export default function ApplicationDocuments({
  application,
  required,
  policy,
  locked,
  changed,
}: {
  application: Application;
  required: DocumentType[];
  policy: SubmissionPolicy | null;
  locked: boolean;
  changed: (version?: number) => Promise<void>;
}) {
  const { data, error, reload } = useResource(
    () =>
      api<{ items: ApplicationDocument[] }>(
        `/applications/${application.id}/documents`,
      ),
    `${application.id}-${application.version}`,
  );
  const [busy, setBusy] = useState(false);
  const [mutationError, setMutationError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<{
    document: ApplicationDocument;
    message: string;
  } | null>(null);
  async function download(document: ApplicationDocument) {
    if (downloading) return;
    setDownloading(true);
    setDownloadError(null);
    try {
      const file = await api<Blob>(
        `/applications/${application.id}/documents/${document.id}`,
        { responseType: "blob" },
      );
      const url = URL.createObjectURL(file);
      const link = window.document.createElement("a");
      link.href = url;
      link.download = document.filename;
      window.document.body.appendChild(link);
      try {
        link.click();
      } finally {
        link.remove();
        // Браузер должен успеть начать скачивание до освобождения URL.
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    } catch (error) {
      setDownloadError({ document, message: errorMessage(error) });
    } finally {
      setDownloading(false);
    }
  }
  const editable =
    application.available_actions.includes("upload_document") && !locked;
  async function mutation(action: () => Promise<number>) {
    if (busy) return;
    setBusy(true);
    setMutationError("");
    try {
      const version = await action();
      await changed(version);
      reload();
    } catch (error) {
      setMutationError(errorMessage(error));
      if (error instanceof ApiError && error.status === 409) setConflict(true);
    } finally {
      setBusy(false);
    }
  }
  async function refresh() {
    setBusy(true);
    try {
      await changed();
      reload();
      setConflict(false);
      setMutationError("");
    } catch (error) {
      setMutationError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }
  async function upload(event: FormEvent<HTMLFormElement>, type: DocumentType) {
    event.preventDefault();
    const form = event.currentTarget;
    const file = new FormData(form).get("file");
    if (!(file instanceof File) || !file.size) {
      setMutationError("Выберите непустой файл");
      return;
    }
    if (!policy) return;
    if (file.size > policy.max_file_size_bytes) {
      setMutationError("Размер файла не должен превышать 10 МиБ");
      return;
    }
    if (!policy.accepted_content_types.includes(file.type)) {
      setMutationError("Выберите PDF, PNG или JPEG");
      return;
    }
    const params = new URLSearchParams({
      document_type: type,
      expected_version: String(application.version),
      filename: file.name,
    });
    await mutation(async () => {
      const result = await api<{
        document: ApplicationDocument;
        application_version: number;
      }>(`/applications/${application.id}/documents?${params}`, {
        method: "POST",
        rawBody: file,
      });
      form.reset();
      return result.application_version;
    });
  }
  function remove(document: ApplicationDocument) {
    void mutation(
      async () =>
        (
          await api<{ application_version: number }>(
            `/applications/${application.id}/documents/${document.id}?expected_version=${application.version}`,
            { method: "DELETE" },
          )
        ).application_version,
    );
  }
  return (
    <section
      className="panel documents-panel"
      aria-labelledby="documents-title"
    >
      <div className="section-top">
        <h2 id="documents-title">Документы</h2>
        <span className="muted">PDF, PNG, JPEG · до 10 МиБ</span>
      </div>
      {downloadError && (
        <div className="notice error download-error" role="alert">
          <p>
            Не удалось скачать «{downloadError.document.filename}».{" "}
            {downloadError.message}
          </p>
          <button
            className="button secondary"
            disabled={downloading}
            onClick={() => void download(downloadError.document)}
          >
            Повторить скачивание
          </button>
        </div>
      )}
      {mutationError && (
        <div className="notice error" role="alert">
          <p>{mutationError}</p>
          {conflict && (
            <button
              className="button secondary"
              disabled={busy}
              onClick={() => void refresh()}
            >
              Загрузить новую версию документов
            </button>
          )}
        </div>
      )}
      {error ? (
        <ErrorPanel error={error} retry={reload} />
      ) : !data ? (
        <Loading />
      ) : (
        <>
          {Object.entries(documentLabels)
            .filter(
              ([type]) =>
                required.includes(type as DocumentType) ||
                data.items.some((item) => item.document_type === type),
            )
            .map(([type, label]) => {
              const files = data.items.filter(
                (item) => item.document_type === type,
              );
              return (
                <div className="document-group" key={type}>
                  <div className="document-heading">
                    <h3>{label}</h3>
                    <span
                      className={files.length ? "document-present" : "muted"}
                    >
                      {files.length ? "Загружено" : "Нужен для отправки"}
                    </span>
                  </div>
                  {files.length > 0 && (
                    <ul className="document-list">
                      {files.map((file) => (
                        <li key={file.id}>
                          <div>
                            <button
                              className="text-link document-download"
                              type="button"
                              disabled={downloading}
                              onClick={() => void download(file)}
                              aria-label={`Скачать ${file.filename}`}
                            >
                              {file.filename}
                            </button>
                            <small>
                              {Math.max(1, Math.ceil(file.size_bytes / 1024))}{" "}
                              КБ · {dateTime(file.created_at)}
                            </small>
                          </div>
                          {editable && (
                            <button
                              className="document-remove"
                              aria-label={`Удалить ${file.filename}`}
                              disabled={busy || conflict}
                              onClick={() => remove(file)}
                            >
                              Удалить
                            </button>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                  {editable && policy && (
                    <DocumentUpload
                      documentType={type as DocumentType}
                      acceptedContentTypes={policy.accepted_content_types}
                      busy={busy}
                      disabled={busy || conflict}
                      onSubmit={(event) =>
                        void upload(event, type as DocumentType)
                      }
                    />
                  )}
                </div>
              );
            })}
        </>
      )}
    </section>
  );
}
