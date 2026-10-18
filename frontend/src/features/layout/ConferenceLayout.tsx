import type { ReactNode } from "react";
import { classes } from "../../components";

export interface ConferenceLayoutProps {
	stage: ReactNode;
	overlay?: ReactNode;
	panel: ReactNode | null;
	controls: ReactNode;
	dialog?: ReactNode;
}

export function ConferenceLayout(props: ConferenceLayoutProps) {
	const { stage, overlay, panel, controls, dialog } = props;

	return (
		<div className="conf">
			<div className="conf__body">
				<div className="conf__stage">
					{stage}
					{overlay && <div className="conf__overlay">{overlay}</div>}
				</div>
				<aside className={classes("conf__panel", !!panel && "conf__panel--open")}>
					<div className="conf__panel-inner">{panel}</div>
				</aside>
			</div>
			{controls}
			{dialog}
		</div>
	);
}
