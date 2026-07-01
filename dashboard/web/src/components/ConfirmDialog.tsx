type Props = {
  title: string;
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
};

export function ConfirmDialog({ title, message, onConfirm, onCancel }: Props) {
  return (
    <div className="modal-backdrop">
      <div className="panel modal">
        <h2>{title}</h2>
        <p>{message}</p>
        <div className="actions">
          <button onClick={onCancel}>取消</button>
          <button onClick={onConfirm}>确认</button>
        </div>
      </div>
    </div>
  );
}
