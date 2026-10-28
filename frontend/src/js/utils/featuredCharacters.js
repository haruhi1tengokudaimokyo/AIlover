/** Keep game portraits equally visible when a fourth character is installed. */
export function featuredCharacters(characters, searchQuery = '') {
  if (searchQuery) return []
  return [...characters]
    .sort((left, right) => Number(Boolean(right.assets?.portrait_url)) - Number(Boolean(left.assets?.portrait_url)))
    .slice(0, 4)
}
