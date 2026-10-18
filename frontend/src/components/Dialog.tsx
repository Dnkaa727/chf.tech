import { Button } from "./Button";
import { Card } from "./Card";

export interface DialogProps {
	title: string;
	text: string;
	confirmLabel: string;
	cancelLabel: string;
	danger?: boolean;
	onConfirm: () => void;
	onCancel: () => void;
}

export function Dialog(props: DialogProps) {
	const {
		title,
		text,
		confirmLabel,
		cancelLabel,
		danger,
		onConfirm,
		onCancel,
	} = props;

	return (
		<div className="dialog" role="dialog" aria-modal="true" aria-label={title}>
			<div className="dialog__body">
				<Card>
					<h2 className="dialog__title">{title}</h2>
					<p className="dialog__text">{text}</p>
					<div className="dialog__actions">
						<Button variant="secondary" onClick={onCancel}>
							{cancelLabel}
						</Button>
						<Button variant={danger ? "danger" : "primary"} onClick={onConfirm}>
							{confirmLabel}
						</Button>
					</div>
				</Card>
			</div>
		</div>
	);
}
