/** The most recent season's row: the last one before "Career" (rows run
 *  oldest first since 8.2.3); Career itself when there is no season. */
export function latestSeasonRow(
  rows: Array<[string, Record<string, unknown>]>,
): [string, Record<string, unknown>] | undefined {
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    if (rows[i][0] !== "Career") return rows[i];
  }
  return rows[0];
}
