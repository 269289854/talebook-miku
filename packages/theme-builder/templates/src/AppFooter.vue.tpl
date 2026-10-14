<template>
    <footer :style="footerStyle">
        <div :style="containerStyle">
            <p :style="textStyle">
                Powered by
                <a
                    href="https://github.com/269289854/talebook-miku"
                    target="_blank"
                    rel="noopener"
                    :style="linkStyle"
                >Talebook</a>
                &nbsp;|&nbsp;
                <a
                    href="https://github.com/269289854/talebook-miku/pkgs/container/talebook-miku"
                    target="_blank"
                    rel="noopener"
                    :style="linkStyle"
                >Docker</a>
            </p>
        </div>
    </footer>
</template>

<script setup>
const footerStyle = {
    borderTop: '1px solid #e0e0e0',
    padding: '20px 16px',
    textAlign: 'center',
    color: '#888',
    fontSize: '13px',
    marginTop: '32px',
    background: '#fafafa',
};

const containerStyle = {
    maxWidth: '1200px',
    margin: '0 auto',
};

const textStyle = {
    margin: '0',
    lineHeight: '1.6',
};

const linkStyle = {
    color: '#1976d2',
    textDecoration: 'none',
};
</script>
