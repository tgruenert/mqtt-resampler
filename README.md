# mqtt-resampler
resamples measure values in configurable intervals

see config.yaml for example

## features
* read mqtt topics with values (only plain values supported at the moment, no JSON)
* wait given interval and calculate an aggregation (sum, avg)
* write calculated values to mqtt with configured name

