import type { ReactNode } from "react";

export interface SplitLayoutProps {
	left: ReactNode;
	right: ReactNode;
}

export function SplitLayout(props: SplitLayoutProps) {
	const { left, right } = props;

	return (
		<div className="split">
			<div>{left}</div>
			<div>{right}</div>
		</div>
	);
}
