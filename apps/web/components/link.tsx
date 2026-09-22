/**
 * next/link without prefetching.
 *
 * Every page fetches its own data in the browser, so prefetching a route buys
 * almost nothing — and a Command Centre with dozens of links was prefetching
 * all of them, keeping one small container busy for ten seconds after every
 * page view, in competition with the API requests the page actually needed.
 */
import NextLink from "next/link";
import type { ComponentProps } from "react";

export default function Link(props: ComponentProps<typeof NextLink>) {
  return <NextLink prefetch={false} {...props} />;
}
