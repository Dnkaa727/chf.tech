import { classes } from "./classes";

export interface AvatarProps {
	name: string;
	size?: "s" | "m" | "xl";
}

const initials = (name: string) =>
	name
		.split(/\s+/)
		.filter(Boolean)
		.slice(0, 2)
		.map((w) => w[0].toUpperCase())
		.join("");

export function Avatar(props: AvatarProps) {
	const { name, size = "m" } = props;

	return (
		<span className={classes("avatar", `avatar--${size}`)} aria-hidden>
			{initials(name)}
		</span>
	);
}
