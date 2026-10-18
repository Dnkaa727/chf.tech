import type { ReactNode } from "react";
import { Card, IconButton } from "../components";

export interface SidePanelProps {
	title: string;
	onClose: () => void;
	children: ReactNode;
}

export function SidePanel(props: SidePanelProps) {
	const { title, onClose, children } = props;

	return (
		<Card padded={false}>
			<div className="side-panel">
				<header className="side-panel__head">
					<h2>{title}</h2>
					<IconButton
						icon="xmark"
						label="Закрыть"
						variant="outline"
						onClick={onClose}
					/>
				</header>
				<div className="side-panel__body">{children}</div>
			</div>
		</Card>
	);
}
