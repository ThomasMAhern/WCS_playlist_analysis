import streamlit as st
import polars as pl

pl.Config.set_tbl_rows(100).set_fmt_str_lengths(100)

regex_year_first = r'\d{2,4}[.\-/ ]?\d{1,2}[.\-/ ]?\d{1,2}'
regex_year_last = r'\d{1,2}[.\-/ ]?\d{1,2}[.\-/ ]?\d{2,4}'
regex_year_abbreviated = r"'\d{2}"

def wcs_specific(df_):
  '''given a df, filter to the records most likely to be west coast swing related'''
  return (df_
          .filter(~(pl.col('name').str.contains(regex_year_first)
                  |pl.col('name').str.contains(regex_year_last)
                  |pl.col('name').str.contains(regex_year_abbreviated)
                  |pl.col('name').str.to_lowercase().str.contains('wcs|social|party|oirée|west coast|routine|blues|practice|practise|bpm|swing|novice|intermediate|comp|musicality|timing|pro show')))
      )

df = (pl.read_parquet('wcs_dj_spotify_playlists.parquet')

      #makes a new column filled with a date - this is good indicator if there was a set played
      .with_columns(extracted_date = pl.concat_list(pl.col('name').str.extract_all(regex_year_last),
                                                    pl.col('name').str.extract_all(regex_year_last),
                                                    pl.col('name').str.extract_all(regex_year_abbreviated),)
                                       .list.unique().list.sort(),
                    song = pl.concat_str('track.name', pl.lit(' - https://open.spotify.com/track/'), 'track.id', ignore_nulls=True),
                    region = pl.col('location').str.split(' - ').list.get(0),)
      
      #gets the counts of djs, playlists, and geographic regions a song is found in
      .with_columns(num_djs = pl.n_unique('owner.display_name').over(pl.col('song')),
                    num_playlists = pl.n_unique('name').over(pl.col('song')),
                    regions = pl.col('region').over('song', mapping_strategy='join')
                                  .list.unique()
                                  .list.drop_nulls()
                                  .list.sort()
                                  .list.join(', '),)
      .with_columns(num_regions = pl.when(pl.col('regions').str.len_bytes() != 0)
                                    .then(pl.col('regions').str.split(', ').list.drop_nulls().list.len())
                                    .otherwise(0))
      )







st.markdown("## Westie DJ-playlist Database:")
st.text("Note: this database lacks most of the non-spotify playlists - but if you know a DJ, pass this to them and tell them they should put their playlists on spotify so we can add them to the collection! (a separate playlist by date is easiest for me ;) )\n")
st.write(f"{df.select(pl.concat_str('track.name', pl.lit(' - '), 'track.id')).unique().shape[0]:,} Songs ({df.pipe(wcs_specific).select(pl.concat_str('track.name', pl.lit(' - '), 'track.id')).unique().shape[0]:,} wcs specific)")
st.write(f"{df.select('track.artists.id').unique().shape[0]:,} Artists ({df.pipe(wcs_specific).select('track.artists.id').unique().shape[0]:,} wcs specific)")
st.write(f"{df.select('name').unique().shape[0]:,} Playlists ({df.pipe(wcs_specific).select('name').unique().shape[0]:,} wcs specific)\n\n")



st.markdown("#### What the data looks like")
st.dataframe(df.sample(100))














st.markdown("#### Enter a Spotify display name or user_id:")
id_input = st.text_input("ex. Kasia Stepek or 1185428002")
dj_id = id_input.lower().strip()

st.markdown(f"#### What popular music doesn't _{id_input}_ play, but others do?")
not_my_music = (df
                #  .pipe(wcs_specific)
                .filter(~pl.col('spotify').str.contains(dj_id)
                        | ~pl.col('owner.display_name').str.to_lowercase().str.contains(dj_id))
                .filter(pl.col('num_djs') > 5,
                        pl.col('num_playlists') > 5)
                .select('song', 'num_djs', 'num_playlists', 'num_regions', 'regions')
                .unique()
                .sort('num_playlists', descending=True)
                )

st.dataframe(not_my_music)


















st.markdown(f"#### What music does only _{id_input}_ play?")

only_i_play = (df
              #  .pipe(wcs_specific)
              .filter(pl.col('num_djs').eq(1)
                      &(pl.col('spotify').str.contains(dj_id)
                        |pl.col('owner.display_name').str.to_lowercase().str.contains(dj_id))
                     )
              .select('song', 'num_djs', 'owner.display_name', 'num_playlists', 'num_regions', 'regions')
              .unique()
              .sort('num_playlists', descending=True)
              )

st.dataframe(only_i_play)












st.markdown(f"#### What are the most popular songs only played in Europe?")
europe = (df
          #  .pipe(wcs_specific)
          .filter(pl.col('regions') == 'Europe')
          .select('song', 'num_djs', 'num_playlists', 'num_regions', 'regions')
          .unique()
          .sort('num_djs', descending=True)
          )

st.dataframe(europe)








st.markdown(f"#### What are the most popular songs only played in USA?")

usa = (df
          #  .pipe(wcs_specific)
          .filter(pl.col('regions') == 'USA')
          .select('song', 'num_djs', 'num_playlists', 'num_regions', 'regions')
          .unique()
          .sort('num_djs', descending=True)
          )

st.dataframe(usa)






st.markdown(f"#### What are the most popular songs only played in Asia?")

asia = (df
          #  .pipe(wcs_specific)
          .filter(pl.col('regions') == 'Asia')
          .select('song', 'num_djs', 'num_playlists', 'num_regions', 'regions')
          .unique()
          .sort('num_djs', descending=True)
          )

st.dataframe(asia)









st.markdown(f"#### What are the most popular songs only played in MENA?")
mena = (df
          #  .pipe(wcs_specific)
          .filter(pl.col('regions') == 'MENA')
          .select('song', 'num_djs', 'num_playlists', 'num_regions', 'regions')
          .unique()
          .sort('num_djs', descending=True)
          )

st.dataframe(mena)





st.text("If you have questions/feedback/suggestions, please leave a comment: \nhttps://forms.gle/19mALUpmM9Z5XCA28")
