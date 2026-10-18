export const classes = (
	...parts: Array<string | false | null | undefined>
): string => parts.filter(Boolean).join(" ");
