import type { ReactNode } from "react";

export interface ScreenProps {
	header?: ReactNode;
	children: ReactNode;
}

export function Screen(props: ScreenProps) {
	const { header, children } = props;

	return (
		<div className="screen">
			{header}
			<main className="screen__main">{children}</main>
		</div>
	);
}
