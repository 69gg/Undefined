import { useEffect } from "react";
import { useTranslation } from "../i18n";

export type ConfirmDialogProps = {
	open: boolean;
	title: string;
	message: string;
	confirmLabel?: string;
	cancelLabel?: string;
	/** 危险操作（如删除）时确认按钮使用红色样式 */
	danger?: boolean;
	onConfirm: () => void;
	onCancel: () => void;
};

/**
 * 通用二次确认弹窗：遮罩点击 / Esc / 取消按钮均关闭，确认按钮触发回调。
 * 复用图片查看器的遮罩交互模式。
 */
export function ConfirmDialog({
	open,
	title,
	message,
	confirmLabel,
	cancelLabel,
	danger = false,
	onConfirm,
	onCancel,
}: ConfirmDialogProps) {
	const { t } = useTranslation();
	// hook 不能用于参数默认值，故在组件内回退到默认文案
	const resolvedConfirmLabel = confirmLabel ?? t("dialog.confirm");
	const resolvedCancelLabel = cancelLabel ?? t("dialog.cancel");

	useEffect(() => {
		if (!open) return;
		const handleKeyDown = (event: KeyboardEvent): void => {
			if (event.key === "Escape") onCancel();
		};
		document.addEventListener("keydown", handleKeyDown);
		return () => document.removeEventListener("keydown", handleKeyDown);
	}, [open, onCancel]);

	if (!open) {
		return null;
	}

	return (
		<div
			className="confirm-dialog-overlay"
			onClick={onCancel}
			onKeyDown={(event) => {
				if (event.key === "Escape") onCancel();
			}}
			role="dialog"
			aria-modal="true"
			aria-label={title}
		>
			<div
				className="confirm-dialog"
				onClick={(event) => event.stopPropagation()}
				onKeyDown={(event) => event.stopPropagation()}
			>
				<h2 className="confirm-dialog-title">{title}</h2>
				<p className="confirm-dialog-message">{message}</p>
				<div className="confirm-dialog-actions">
					<button className="ghost-button" onClick={onCancel} type="button">
						{resolvedCancelLabel}
					</button>
					<button
						className={danger ? "danger-button" : "primary-button"}
						onClick={onConfirm}
						type="button"
					>
						{resolvedConfirmLabel}
					</button>
				</div>
			</div>
		</div>
	);
}
