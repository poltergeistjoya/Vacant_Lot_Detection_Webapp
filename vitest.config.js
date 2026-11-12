export default {
  define: {
    // Tests pass base URL / available sources explicitly; these are just defaults
    '__PMTILES_BASE_URL__': JSON.stringify(''),
    '__PMTILES_SOURCES__': JSON.stringify(['both', 'pluto_nonvacant', 'model_levels']),
  },
  test: {
    include: ['tests/js/**/*.test.js'],
    environment: 'node',
  },
};
