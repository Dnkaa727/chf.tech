import type { ReactNode } from "react";
import { classes } from "./classes";

export interface BadgeProps {
	tone?: "tonal" | "accent" | "neutral";
	children: ReactNode;
}

export function Badge(props: BadgeProps) {
	const { tone = "tonal", children } = props;

	return <span className={classes("badge", `badge--${tone}`)}>{children}</span>;
}
