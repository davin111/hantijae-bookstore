import React, { Component } from 'react';
import Grid from '@material-ui/core/Grid';
import Button from '@material-ui/core/Button';
import FacebookIcon from '@material-ui/icons/Facebook';
import InstagramIcon from '@material-ui/icons/Instagram';
import TwitterIcon from '@material-ui/icons/Twitter';
import NotesIcon from '@material-ui/icons/Notes';

import './Footer.css';

interface Props {
  history: any;
}

// eslint-disable-next-line react/prefer-stateless-function
class Footer extends Component<Props> {
  render() {
    return (
      <div className="WholeFooter">
        <hr className="FooterLine" />
        <footer>
          <div className="FooterInfo">
            {/* <div className="LeftFooter">
              도서출판 한티재
            </div>
            <div className="RightFooter">
              그렇다
            </div> */}
            <>
              <Grid container spacing={5}>
                {/* <Grid item xs={12} sm={12}>
                  <Typography variant="h6" gutterBottom>
                    주문 정보 입력
                  </Typography>
                </Grid> */}
                <Grid item xs={12} sm={6}>
                  <div className="FooterButtons">
                    <Button
                      type="button"
                      variant="contained"
                      color="default"
                      size="small"
                      onClick={() => window.open('http://blog.naver.com/hanti_books')}
                      endIcon={<NotesIcon />}
                    >
                      한티재 Blog
                    </Button>
                    <div className="ButtonGap" />
                    <Button
                      type="button"
                      variant="contained"
                      color="default"
                      size="small"
                      onClick={() => window.open('https://www.facebook.com/hantijae')}
                      endIcon={<FacebookIcon />}
                    >
                      한티재 Facebook
                    </Button>
                    <div className="ButtonGap" />
                    <Button
                      type="button"
                      variant="contained"
                      color="default"
                      size="small"
                      onClick={() => window.open('https://www.instagram.com/hantijae')}
                      endIcon={<InstagramIcon />}
                    >
                      한티재 Instagram
                    </Button>
                    <div className="ButtonGap" />
                    <Button
                      type="button"
                      variant="contained"
                      color="default"
                      size="small"
                      onClick={() => window.open('https://twitter.com/hantijae_book')}
                      endIcon={<TwitterIcon />}
                    >
                      한티재 Twitter
                    </Button>
                  </div>
                </Grid>
                <Grid item xs={12} sm={6}>
                  <div className="FooterDetailInfo">
                    42087 대구시 수성구 달구벌대로 492길 15
                    <br />
                    TEL 053-743-8368 | FAX 053-743-8367
                    <br />
                    Email hantibooks@gmail.com
                    <br />
                    Copyright © Hantijae publisher. All Rights Reserved.
                  </div>
                </Grid>
              </Grid>
            </>
          </div>
        </footer>
      </div>
    );
  }
}

export default Footer;
