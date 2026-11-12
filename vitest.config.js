export default {
  define: {
    // Tests pass available sources explicitly; this is just the default
    '__PMTILES_SOURCES__': JSON.stringify(['both', 'pluto_nonvacant', 'model_levels']),
  },
  test: {
    include: ['tests/js/**/*.test.js'],
    environment: 'node',
  },
};
