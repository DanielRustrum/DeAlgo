-- Reading a condition's own fields, which arrive as text.

local M = {}

-- A field as a number, or `fallback` when it is empty or not one.
function M.number(settings, name, fallback)
  local given = tonumber(settings[name])
  if given == nil then return fallback end
  return given
end

return M
